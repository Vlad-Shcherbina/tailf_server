import logging
import http
import time
import urllib
import os
import shutil
import mimetypes
import json
import html
import argparse
from pathlib import Path
from http import server

FOLLOW_TEMPLATE = '''
<script>
  let last_scroll_y = window.scrollY;
  let follow = true;
  function scroll(e) {
    if (window.scrollY < last_scroll_y) {
      follow = false;
    } else if (window.innerHeight + window.scrollY >= document.body.offsetHeight) {
      follow = true;
    }
    last_scroll_y = window.scrollY;
  }
  let scroll_event_listener_added = false;

  let event_source = new EventSource(%s);
  event_source.addEventListener('append', function(e) {
    document.write(JSON.parse(e.data));
    if (!scroll_event_listener_added) {
        // have to do it after document is recreated by document.write()
        window.addEventListener('scroll', scroll);
        scroll_event_listener_added = true;
    }
    if (follow) {
      window.scrollTo(0, document.body.scrollHeight);
    }
  });
  event_source.onerror = function(err) {
    console.log('error', err);
    event_source.close();
  };
</script>
'''

class Handler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        logging.info(f'GET {self.path}')

        orig_path, _, args = self.path.partition('?')

        path = urllib.parse.unquote(orig_path)
        path = Path(os.getcwd() + path).resolve()

        cur_dir_parts = Path.cwd().parts
        if path.parts[:len(cur_dir_parts)] != cur_dir_parts:
            logging.error(f'path {path} is outside cur dir')
            return
        path = path.relative_to(Path.cwd())
        logging.info(path)

        if not path.exists() or path.is_dir():
            self.send_response(http.HTTPStatus.NOT_FOUND)
            self.end_headers()
            return

        content_type, _ = mimetypes.guess_type(str(path))
        logging.info(content_type)

        if not args:
            self.send_response(http.HTTPStatus.OK)
            self.send_header('Content-Type', content_type)
            self.end_headers()
            shutil.copyfileobj(path.open('rb'), self.wfile)

        elif args == 'follow':
            self.send_response(http.HTTPStatus.OK)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write((FOLLOW_TEMPLATE % json.dumps(orig_path + '?sse')).encode('ascii'))

        elif args == 'sse':
            self.send_response(http.HTTPStatus.OK)
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            if content_type != 'text/html':
                self.wfile.write(b'event: append\ndata: "<pre>"\n\n')
            fin = path.open('r', encoding='utf-8')
            last_send_time = time.time()
            last_read_time = time.time()
            while True:
                data = fin.read()
                if data:
                    last_read_time = time.time()
                    logging.info(f'update for {path}')
                    if content_type != 'text/html':
                        data = html.escape(data)
                    data = json.dumps(data)
                    data = data.encode('ascii')
                    try:
                        self.wfile.write(b'event: append\ndata: ' + data + b'\n\n')
                    except ConnectionAbortedError:
                        logging.warning('connection aborted')
                        return
                    last_send_time = time.time()
                    continue
                if time.time() > last_send_time + 30:
                    try:
                        logging.info(f'keep alive {path}')
                        self.wfile.write(b': keep alive\n\n')
                    except ConnectionAbortedError:
                        logging.warning('connection aborted')
                        return
                    last_send_time = time.time()
                dt = time.time() - last_read_time
                if dt < 5:
                    time.sleep(0.5)
                elif dt < 30:
                    time.sleep(1)
                else:
                    time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()

    addr = '', args.port
    with server.ThreadingHTTPServer(addr, Handler) as s:
        logging.info(f'Serving at http://localhost:{args.port}')
        s.serve_forever()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname).1s %(asctime)s %(module)10.10s:%(lineno)-4d (%(threadName)-11.11s) %(message)s')
    main()
