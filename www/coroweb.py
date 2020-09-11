import asyncio,os,inspect,logging,functools

from urllib import parse
from aiohttp import web


def get(path):
    '''
    Define decorator @get('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper
    return decorator

def post(path):
    '''
    Define decorator @post('/path')
    '''
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator

def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

def has_request_arg(fn):
    sig = inspect.signature(fn)#inspect.Signature函数签名对象
    params = sig.parameters#为dict，里面包含了参数
    found = False
    for name, param in params.items():#参数共有5种类型 必须位置参数，可位置可关键字参数，可变位置参数，必须关键字参数，可变关键字参数
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found

class RequestHandler(object):#fn为主，request为副，副以主要求为准传递数据
    def __init__(self,app,fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)#检验URL处理函数的参数,检查是否有request名字的参数
        self._has_var_kw_arg = has_var_kw_arg(fn)#检验函数是否有 可变关键字参数
        self._has_named_kw_args = has_named_kw_args(fn)#检验是否有 必须关键字参数
        self._named_kw_args = get_named_kw_args(fn)# 拿到 必须关键字参数
        self._required_kw_args = get_required_kw_args(fn)#拿到 要求的必须关键字参数

    async def __call__(self,request):#RequestHandler实例对所有的URL处理函数都有了充分的理解与处理后，等待确定了method和path的request传入后交给对应fn
        kw = None
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:#该URL处理函数有 可变关键字参数或必须关键字参数
            if request.method == 'POST':#判断传入的 request 属于哪一路后 提取出 request中的数据
                if not request.content_type:# None时，排除异常
                    return web.HTTPBadRequest("Missing Content-Type")
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = await request.json()
                    if not isinstance(params,dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)#POST法最终出来的是一个 dict
                else:
                    return web.HTTPBadRequest("Unsupported Content-Type: %s"%request.content_type)
            if request.method == "GET":
                qs = request.query_string
                if qs:
                    kw = dict()#GET法最终出来的是一个 dict
                    for k,v in parse.parse_qs(qs,True).items():
                        kw[k] = v[0]
        if kw is None:#不是 POST和 GET请求
            kw = dict(**request.match_info)
        else:
            if not self._has_var_kw_arg and self._named_kw_args:#进一步筛选 同时有 可变关键参和必须关键参的
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy

            for k,v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s'%k)
                kw[k] = v
        if self._has_request_arg:#有 request命名的参数的处理函数则继续添加参数至kw
            kw['request'] = request
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s'%name)
        logging.info('call with args: %s'%str(kw))
        try:#以上就是将request中的相关参数提取出来后对应 fn
            r = await self._func(**kw)#URL处理函数连接点
            return r
        except:
            return dict(error = "ApiError")


def add_route(app,fn):
    method = getattr(fn,'__method__',None)
    path = getattr(fn,'__route__',None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.'% str(fn))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)'%(method,path,fn.__name__,', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method,path,RequestHandler(app,fn))#参考app.py里的内容，关键点在注册好后调用，这里是全自动扫描注册,都是依据此语句构建的框架
    #貌似 RequestHandler(app,fn)只是初始化了一个实例，每一个路径都对应一个实例，该实例引用有call函数等待request传来后被RequestHandler(app,fn)(request)调用
    #即将处理函数fn接入到Web.app中,RequestHandler的初始化都是检查fn的，即server端，只待request的到来.
    #method和path的确定就选定了对应的URL处理函数了

def add_routes(app,module_name):#专门将一整个py文件中的函数动态加载为 URL处理函数
    n = module_name.rfind('.')
    if n == (-1):
        mod = __import__(module_name,globals(),locals())#某模块内容经常变化，则用__import__动态加载
    else:
        name = module_name[n+1:]#拿到后缀名  handler.py 中的py
        mod = getattr(__import__(module_name[:n],globals(),locals(),[name]),name)#不对的
    for attr in dir(mod):#双重过滤，过滤掉下划线符号的和没有 __method__及__route__的属性
        if attr.startswith('_'):
            continue
        fn = getattr(mod,attr)#从模块中拿出指定的函数索引
        if callable(fn):
            method= getattr(fn,'__method__',None)#从函数中拿出指定的特性
            path=getattr(fn,'__route__',None)
            if method and path:
                add_route(app,fn)

def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),'static')
    app.router.add_static('/static/',path)
    logging.info('add static %s=>%s'%('/static/',path))

