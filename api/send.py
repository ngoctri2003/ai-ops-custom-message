from app import web


class handler(web.BaseHandler):
    def do_POST(self):
        self.serve(web.r_send, post=True)
