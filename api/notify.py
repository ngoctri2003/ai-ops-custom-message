from app import web


class handler(web.BaseHandler):
    def do_POST(self):
        self.serve_machine(web.r_notify)
