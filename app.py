import os,json,uuid,asyncio
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from ai_router import AIManager
load_dotenv(); ROOT=Path(__file__).parent; DATA=ROOT/'data'; REPORTS=DATA/'reports'; REPORTS.mkdir(parents=True,exist_ok=True)
ANS=DATA/'answers.json'; TESTS=DATA/'test_cases.json'
for p,d in [(ANS,{'version':1,'answers':[]}),(TESTS,{'version':1,'tests':[]})]:
 if not p.exists(): p.write_text(json.dumps(d,indent=2),encoding='utf-8')
app=FastAPI(title='AI Web Testing Agent'); app.mount('/static',StaticFiles(directory=str(ROOT/'static')),name='static')
pw=browser=context=page=None; lock=asyncio.Lock(); ai=AIManager()
def readj(p,d):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except:return d
def writej(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def now():return datetime.now(timezone.utc).isoformat()
class Navigate(BaseModel):url:str
class Command(BaseModel):command:str=Field(min_length=1,max_length=3000)
class Answer(BaseModel):question:str;answer:str;expected:str|None=None;notes:str=''
class Execute(BaseModel):plan:dict;confirmed:bool=False
@app.on_event('startup')
async def start():
 global pw,browser
 pw=await async_playwright().start(); browser=await pw.chromium.launch(headless=os.getenv('HEADLESS','false').lower()=='true')
@app.on_event('shutdown')
async def stop():
 global pw,browser,context
 for x in (context,browser):
  if x:
   try:await x.close()
   except:pass
 if pw:
  try:await pw.stop()
  except:pass
@app.get('/',response_class=HTMLResponse)
async def home():return (ROOT/'static/index.html').read_text(encoding='utf-8')
@app.get('/api/status')
async def status():return {'browser_started':bool(browser and browser.is_connected()),'page_open':bool(page and not page.is_closed()),'ai_providers':ai.status()}
async def inspect_page():
 if not page or page.is_closed():return {'error':'لا توجد صفحة مفتوحة'}
 return await page.evaluate('''() => {const vis=e=>{let r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};const label=e=>(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.getAttribute('title')||e.value||'').trim().replace(/\\s+/g,' ').slice(0,160);let els=[...document.querySelectorAll('button,a,input,textarea,select,[role=button],[contenteditable=true]')].filter(vis).slice(0,160);return {title:document.title,url:location.href,headings:[...document.querySelectorAll('h1,h2,h3')].filter(vis).slice(0,20).map(label),elements:els.map((e,index)=>({index,tag:e.tagName.toLowerCase(),type:e.getAttribute('type')||'',text:label(e),placeholder:e.getAttribute('placeholder')||'',disabled:!!e.disabled})),bodyText:(document.body?.innerText||'').slice(0,4000)}}''')
@app.post('/api/navigate')
async def navigate(b:Navigate):
 global context,page
 u=urlparse(b.url.strip())
 if u.scheme not in ('http','https') or not u.hostname:raise HTTPException(400,'أدخل رابطًا صحيحًا يبدأ بـ http:// أو https://')
 async with lock:
  if context:
   try:await context.close()
   except:pass
  context=await browser.new_context(viewport={'width':1440,'height':900});page=await context.new_page();page.set_default_timeout(8000)
  try:await page.goto(b.url.strip(),wait_until='domcontentloaded',timeout=30000);return {'ok':True,'url':page.url,'title':await page.title(),'inspection':await inspect_page()}
  except Exception as e:return {'ok':False,'error':str(e),'url':page.url,'inspection':await inspect_page()}
@app.get('/api/inspect')
async def inspect():return await inspect_page()
@app.post('/api/command')
async def plan(b:Command):
 if not page or page.is_closed():raise HTTPException(400,'افتح موقعًا أولًا')
 ins=await inspect_page(); p=await ai.plan(b.command,ins);return {'command':b.command,'plan':p,'inspection':ins}
@app.post('/api/execute')
async def execute(b:Execute):
 if not page or page.is_closed():raise HTTPException(400,'افتح الموقع أولًا')
 p=b.plan;a=p.get('action');r={'ok':False,'action':a,'at':now()}
 try:
  if a=='inspect':r.update(ok=True,message='تم فحص الصفحة')
  elif a=='wait':
   ms=max(0,min(int(p.get('milliseconds',1000)),10000));await page.wait_for_timeout(ms);r.update(ok=True,message=f'انتظار {ms}ms')
  elif a in ('click','fill'):
   if not b.confirmed:return {'needs_confirmation':True,'message':'أكد تنفيذ التفاعل قبل المتابعة','plan':p}
   selector='button,a,input,textarea,select,[role=button],[contenteditable=true]' if a=='click' else 'input,textarea,select,[contenteditable=true]'
   els=await page.locator(selector).all();i=int(p.get('index',-1))
   if i<0 or i>=min(len(els),300):raise ValueError('رقم العنصر غير صالح')
   if not await els[i].is_visible():raise ValueError('العنصر غير ظاهر')
   if a=='click':await els[i].click();r.update(ok=True,message='تم الضغط')
   else:await els[i].fill(str(p.get('value','')));r.update(ok=True,message='تم ملء الحقل')
  elif a=='press':
   key=str(p.get('key','Enter'))
   if key not in ('Enter','Tab','Escape','ArrowDown','ArrowUp','Control+Enter'):raise ValueError('مفتاح غير مسموح')
   if not b.confirmed:return {'needs_confirmation':True,'message':'أكد ضغط المفتاح','plan':p}
   await page.keyboard.press(key);r.update(ok=True,message='تم ضغط '+key)
  else:raise ValueError('الإجراء غير مدعوم؛ لا يتم تشغيل JavaScript عشوائي')
  r['inspection']=await inspect_page(); report={'id':uuid.uuid4().hex,'created_at':now(),'plan':p,'result':r};writej(REPORTS/(report['id']+'.json'),report);return r
 except Exception as e:r['error']=str(e);r['inspection']=await inspect_page();return r
@app.get('/api/answers')
async def answers():return readj(ANS,{'version':1,'answers':[]})
@app.post('/api/answers')
async def add_answer(b:Answer):
 d=readj(ANS,{'version':1,'answers':[]});rec={'id':uuid.uuid4().hex,'question':b.question,'answer':b.answer,'expected':b.expected,'notes':b.notes,'created_at':now(),'verified':False};d['answers'].append(rec);writej(ANS,d);return rec
@app.get('/api/reports')
async def reports():
 out=[]
 for f in sorted(REPORTS.glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:100]:
  try:out.append(json.loads(f.read_text(encoding='utf-8')))
  except:pass
 return {'reports':out}
@app.get('/api/report-file/{name}')
async def report_file(name:str):
 if '/' in name or '\\' in name or not name.endswith('.png'):raise HTTPException(400,'اسم ملف غير صالح')
 p=REPORTS/name
 if not p.exists():raise HTTPException(404,'غير موجود')
 return FileResponse(p)
@app.get('/api/screenshot')
async def screenshot():
 if not page or page.is_closed():raise HTTPException(400,'افتح موقعًا أولًا')
 p=REPORTS/('screen_'+uuid.uuid4().hex[:8]+'.png');await page.screenshot(path=str(p),full_page=True);return {'url':'/api/report-file/'+p.name}
