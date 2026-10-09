import os,json,httpx
PROVIDERS=[('openrouter','OPENROUTER_API_KEY',os.getenv('OPENROUTER_BASE_URL','https://openrouter.ai/api/v1'),os.getenv('OPENROUTER_MODEL','meta-llama/llama-3.3-70b-instruct:free')),('groq','GROQ_API_KEY',os.getenv('GROQ_BASE_URL','https://api.groq.com/openai/v1'),os.getenv('GROQ_MODEL','llama-3.3-70b-versatile')),('nvidia','NVIDIA_API_KEY',os.getenv('NVIDIA_BASE_URL','https://integrate.api.nvidia.com/v1'),os.getenv('NVIDIA_MODEL','meta/llama-3.3-70b-instruct'))]
class AIManager:
 def status(self):return [{'name':n,'configured':bool(os.getenv(k)),'model':m} for n,k,b,m in PROVIDERS]
 async def ask(self,system,user):
  last=None
  for name,key,base,model in PROVIDERS:
   if not os.getenv(key):continue
   try:
    async with httpx.AsyncClient(timeout=35) as c:
     r=await c.post(base.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+os.environ[key]},json={'model':model,'temperature':0.1,'max_tokens':700,'messages':[{'role':'system','content':system},{'role':'user','content':user}]});r.raise_for_status();return {'provider':name,'text':r.json()['choices'][0]['message']['content']}
   except Exception as e:last={'provider':name,'error':str(e)}
  return last
 async def plan(self,command,inspection):
  sys='أنت مخطط لأتمتة اختبار واجهات ويب مصرح بها. أخرج JSON فقط: action,index,value,key,milliseconds,explanation. الإجراءات المسموحة inspect/click/fill/press/wait. اختر index من عناصر الفحص فقط. عند الغموض استخدم inspect واسأل للتوضيح. لا تقترح حذف أو شراء أو إرسال نهائي، ولا تشغل JavaScript عشوائيًا. index يبدأ من صفر.'
  raw=await self.ask(sys,json.dumps({'command':command,'page':inspection},ensure_ascii=False))
  if not raw or 'text' not in raw:return {'action':'inspect','explanation':'لم ينجح أي مزود AI مهيأ. أضف مفتاحًا في .env أو افحص الصفحة يدويًا.','ai_error':raw}
  try:
   t=raw['text'];p=json.loads(t[t.find('{'):t.rfind('}')+1]);p['original_command']=command
   if p.get('action') not in ('inspect','click','fill','press','wait'):raise ValueError()
   return p
  except:return {'action':'inspect','explanation':'تعذر استخراج خطة آمنة من رد AI. أعد صياغة الأمر.','provider':raw['provider']}
