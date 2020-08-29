import  config_default

class Dict(dict):#转变为 x.y 的引用方式
    def __init__(self,names=(),values=(),**kw):
        super().__init__(**kw)
        for k,v in zip(names,values):
            self[k] = v

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"Dict object has no attribute '%s' "%key)

    def __setattr__(self, key, value):
        self[key] = value

def toDict(d):
    D = Dict()
    for k,v in d.items():
        D[k] = toDict(v) if isinstance(v,dict) else v
    return D

def merge(defaults,override):
    r = {}
    for k,v in defaults.items():
        if k in override:
            if isinstance(v,dict):
                r[k] = merge(v,override[k])
            else:
                r[k] = override[k]
        else:
            r[k] = v
    return r



configs = config_default.configs

try:
    import config_override
    configs = merge(configs,config_override.configs)#对应替换
except ImportError:
    pass


configs = toDict(configs)