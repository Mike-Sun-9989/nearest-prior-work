"""Explicit browser acceptance-test server, loopback only. No real provider calls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
import httpx
from model_fixture import fake_model


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.reply(200,{'data':[{'id':m} for m in ['demo-chat','empty-reply','wrong-key','slow-reply']]})
    def reply(self,status,data):
        content=json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers()
        try:self.wfile.write(content)
        except OSError:pass
    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']))
        body=json.loads(raw)
        if body.get('model')=='empty-reply':return self.reply(200,{})
        if body.get('model')=='wrong-key':return self.reply(401,{'error':'invalid'})
        if body.get('model')=='slow-reply':time.sleep(20)
        response=fake_model([]).handle_request(httpx.Request('POST','http://localhost/v1/chat/completions',content=raw))
        self.reply(response.status_code,response.json())


if __name__=='__main__':
    print('Local test API at 127.0.0.1:8899; no external calls.',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8899),Handler).serve_forever()
