from app import web


class handler(web.BaseHandler):
    def do_GET(self):
        self.serve(web.r_scheduled, post=False)
