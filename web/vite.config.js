import {defineConfig} from 'vite';
import {bcbProxy} from './server/bcb.js';
export default defineConfig({base:'/tomaconta/',plugins:[{name:'bcb-local',configureServer(server){server.middlewares.use(async(req,res,next)=>{if(!req.url.startsWith('/tomaconta/api/bcb'))return next();const r=await bcbProxy(new URL(req.url,'http://localhost'));res.statusCode=r.status;r.headers.forEach((v,k)=>res.setHeader(k,v));res.end(await r.text());});}}],build:{rollupOptions:{output:{manualChunks:{charts:['echarts'],react:['react','react-dom']}}}}});
