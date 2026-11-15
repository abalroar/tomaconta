import {defineConfig} from 'vite';
import {bcbProxy} from './server/bcb.js';
import {handleShared,SHARED_ROOT} from './server/shared.js';

export default defineConfig({
  base:'/atlas-sfn/',
  plugins:[{
    name:'tomaconta-local-api',
    configureServer(server){
      server.middlewares.use(async(req,res,next)=>{
        const url=new URL(req.url,'http://localhost');
        if(url.pathname.startsWith('/atlas-sfn/api/'))url.pathname=url.pathname.replace('/atlas-sfn/api/','/tomaconta/api/');
        let response;
        if(url.pathname.startsWith(`${SHARED_ROOT}/`)){
          // Development has no financial bindings. The real handler reports
          // static mode explicitly and rejects refresh requests until configured.
          response=await handleShared(new Request(url,{method:req.method}),{});
        }else if(url.pathname==='/tomaconta/api/bcb'){
          response=await bcbProxy(url);
        }else return next();
        res.statusCode=response.status;
        response.headers.forEach((value,key)=>res.setHeader(key,value));
        res.end(await response.text());
      });
    },
  }],
  build:{rollupOptions:{output:{manualChunks:{charts:['echarts'],react:['react','react-dom']}}}},
});
