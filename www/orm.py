
import time
import uuid
import logging;logging.basicConfig(level=logging.INFO)
import asyncio
import aiomysql

# async/await是在python3.5版么以及之后的版本中才能使用。2. async不能和yield同时使用。3.await只能作用于可等待对象
#async/await的出现是为了协程，是为了区分生成器使编程更加明确,来提升Python中的异步编程体验

@asyncio.coroutine
def create_pool(loop,**kw):
    logging.info('create database connection pool...')
    global __pool
    __pool = yield from aiomysql.create_pool(
        host = kw.get('host','localhost'),
        port = kw.get('port',3306),
        user = kw['user'],
        password = kw['password'],
        db = kw['db'],
        charset = kw.get('charset','utf8'),
        autocommit = kw.get('autocommit',True),
        maxsize = kw.get('maxsize',10),
        minsize = kw.get('minsize',1),
        loop = loop

    )

@asyncio.coroutine
def select(sql,args,size=None):
    # log(sql,args)
    global __pool
    with (yield from __pool) as conn:
        cur = yield from conn.cursor(aiomysql.DictCursor)
        yield from cur.execute(sql.replace('?',"%s"),args or ())
        if size:
            rs = yield from cur.fetchmany(size)
        else:
            rs = yield from cur.fetchall()
        yield from cur.close()
        logging.info('rows returned: %s'% len(rs))
        return rs

@asyncio.coroutine
def execute(sql,args):
    # log(sql)
    with (yield from __pool) as conn:
        try:
            cur = yield from conn.cursor()
            yield from cur.execute(sql.replace('?','%s'),args)
            affected = cur.rowcount
            yield from cur.close()
        except BaseException as e:
            raise
        return affected


class ModelMetaclass(type):

    def __new__(cls, name,bases,attrs):
        if name == 'Model':#若传过来的是Model类则原封不动
            return type.__new__(cls,name,bases,attrs)
        tableName = attrs.get('__table__',None) or name
        logging.info('found model: %s (table: %s)'%(name,tableName))
        mappings = dict()
        fields = []
        primaryKey = None
        for k,v in attrs.items():
            if isinstance(v,Field):
                logging.info('  found mapping: %s ==> %s'%(k,v))
                mappings[k] = v
                if v.primary_key:
                    if primaryKey:
                        raise RuntimeError("Duplicate primary key for field: %s"%k)
                    primaryKey = k
                else:
                    fields.append(k)

        if not primaryKey:
            raise RuntimeError("Primary key not found.")
        for k in mappings.keys():#之所以删除是为了实例传入参数后腾位置避免对应属性被覆盖掉
            attrs.pop(k)
        escaped_fields = list(map(lambda f:'`%s`'%f,fields))#装的是除主键外的其它列名
        attrs['__mappings__'] = mappings#划分个子部分归拢全部参数类型的属性,保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey#主键只可能有一个
        attrs['__fields__'] = fields
        attrs['__select__'] = 'select `%s`,%s from `%s`'%(primaryKey,', '.join(escaped_fields),tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)'%(tableName,', '.join(escaped_fields),primaryKey,create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?'%(tableName,', '.join(map(lambda f:'`%s` =?'%(mappings.get(f).name or f),fields)),primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?'%(tableName,primaryKey)
        return type.__new__(cls,name,bases,attrs)




class Model(dict,metaclass=ModelMetaclass):

    def __init__(self,**kw):
        super(Model,self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except:
            raise AttributeError(r"'Model' object has no attribute '%s'"%key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self,key):#拿到User实例传过来的参数值
        return getattr(self,key,None)

    def getValueOrDefault(self,key):
        value = getattr(self,key,None)#拿到User实例传过来的参数值
        if value is None:#若User实例没有设置某个列的值则取默认值
            field = self.__mappings__[key]#拿到类对象中存储的对应列对象索引,比如 name 为 StringFeild对象索引
            if field.default is not None:#经由该对象索引拿到预先设置的该列的默认值并设置好
                value = field.default() if callable(field.default) else field.default#默认值有可能是可调用的对象
                logging.debug('useing default value for %s:%s')%(key,str(value))
                setattr(self,key,value)
        return value

    def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = yield from execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = yield from execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = yield from execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)

    @classmethod
    @asyncio.coroutine
    def find(cls,pk):
        rs = yield from select('%s where `%s`=?'%(cls.__select__,cls.__primary_key__),[pk],1)
        if len(rs)==0:
            return None
        return cls(**rs[0])

def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)

class Field(object):

    def __init__(self,name,column_type,primary_key,default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>'%(self.__class__.__name__,self.column_type,self.name)


class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)


def next_id():
    return '%015d%s000'%(int(time.time()*1000),uuid.uuid4().hex)

class User(Model):
    __table__ = 'users'
    id = StringField(primary_key=True,default=next_id)
    email = StringField(ddl='varchar(50)')
    passwd = StringField(ddl='varchar(50)')
    admin = BooleanField()
    name = StringField(ddl='varchar(50)')
    image = StringField(ddl='varchar(500)')
    created_at = FloatField(default=time.time)


class IntegerField(Field):
    def __init__(self,name):
        super().__init__(name,'bigint')


if __name__ == '__main__':
    user = User(id=12345, name='Michael', email='test@orm.org', password='my-pwd')
    user.save()