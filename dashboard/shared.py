"""Local frontend using the production API; no local database or workers."""
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

PRODUCTION = 'https://trader.manojmathivanan.com'
WEB = Path(__file__).resolve().parent / 'web'
REQUEST_HEADERS = {'accept', 'accept-encoding', 'content-type', 'cookie',
                   'authorization', 'x-trader-request'}
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate',
               'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'}


def create_app(*, transport=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if (request.client.host not in ('127.0.0.1', '::1', 'testclient') or
                request.url.hostname not in ('localhost', '127.0.0.1', '::1', 'testserver')):
            return JSONResponse({'detail': 'The shared frontend is loopback-only.'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if (request.headers.get('x-trader-request') != 'local-ui' or
                    (origin and origin != str(request.base_url).rstrip('/'))):
                return JSONResponse({'detail': 'Use the local dashboard for this action.'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer'})
        return response

    @app.get('/')
    def index():
        return FileResponse(WEB / 'index.html')

    @app.api_route('/api/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    async def proxy(request: Request, path: str):
        url = httpx.URL(PRODUCTION).copy_with(path=request.url.path,
                                              query=request.url.query.encode('ascii') or None)
        headers = {key: value for key, value in request.headers.items() if key in REQUEST_HEADERS}
        headers['origin'] = PRODUCTION
        try:
            # Per-request clients keep sessions from being shared through a proxy cookie jar.
            # Never retry mutations: a timeout may occur after production committed them.
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(120, connect=10),
                                         follow_redirects=False, trust_env=False) as client:
                upstream = await client.request(request.method, url, headers=headers,
                                                content=await request.body())
        except httpx.HTTPError:
            return JSONResponse({'detail': 'The shared production service is unavailable. '
                                 'Check the website or your connection before retrying.'}, status_code=502)
        response = Response(upstream.content, status_code=upstream.status_code)
        excluded = HOP_HEADERS | {'content-length', 'content-encoding', 'set-cookie'}
        excluded.update(part.strip().lower() for part in upstream.headers.get('connection', '').split(','))
        for key, value in upstream.headers.multi_items():
            if key not in excluded:
                response.headers.append(key, value)
        for value in upstream.headers.get_list('set-cookie'):
            cookies = SimpleCookie()
            cookies.load(value)
            for cookie in cookies.values():
                # Production stays HTTPS. Only this loopback frontend uses HTTP cookies.
                cookie['secure'] = ''
                cookie['domain'] = ''
                response.headers.append('set-cookie', cookie.OutputString())
        return response

    app.mount('/static', StaticFiles(directory=WEB), name='static')
    return app


app = create_app()
