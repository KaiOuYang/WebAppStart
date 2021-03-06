# !/usr/bin/env python3
# -*- coding: utf-8 -*-


import asyncio, logging

import aiomysql


def log(sql, args=()):
    logging.info('SQL: %s' % sql)


async def create_pool(loop, **kw):#异步连接池不用同步等待，不必频繁打开或关闭数据库连接，尽量复用
    logging.info('create database connection pool...')
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
    )

# async/await是在python3.5版么以及之后的版本中才能使用。2. async不能和yield同时使用。3.await只能作用于可等待对象
#async/await的出现是为了协程，是为了区分生成器使编程更加明确,来提升Python中的异步编程体验
async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    async with __pool.get() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql.replace('?', '%s'), args or ())
            if size:
                rs = await cur.fetchmany(size)
            else:
                rs = await cur.fetchall()
        logging.info('rows returned: %s' % len(rs))
        return rs


async def execute(sql, args, autocommit=True):
    log(sql)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            raise
        return affected


def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)


class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


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


class ModelMetaclass(type):#目的是产生一个类实例，传递给子类init

    def __new__(cls, name, bases, attrs):#如User类传入，则name='User',attrs为User类中定义的属性，bases为包含orm.Model类的元组
        if name == 'Model':#若传过来的是Model类则原封不动
            return type.__new__(cls, name, bases, attrs)#返回的是类实例，类似于类产生实例那样，此刻由type类产生类，而cls为ModelMetaclass
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()#存放过滤出的 Field类 属性键与键值
        fields = []#存放除主键外的Field类 属性键
        primaryKey = None#存放具有主键属性的 键值
        for k, v in attrs.items():#过滤出需要的 参数类键和键值
            if isinstance(v, Field):#检查属性值是否是 自己定义的参数类Field
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键:
                    if primaryKey:#主键唯一判断
                        raise Exception('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:#必须要有主键
            raise Exception('Primary key not found.')
        for k in mappings.keys():#之所以删除是为了实例传入参数后腾位置避免对应属性被覆盖掉
            attrs.pop(k)#从原来的类属性字典attrs中删除掉 所有的 Field类 的属性键与键值
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))#变形除主键外的其它列名,即两边加上了符号``
        #总的来说，attrs去掉了一块Field类的属性键(无论主键)，保存到了mappings中，而fields存放无主键属性的键，primaryKey存放有主键属性的键
        #然后开始再attrs中创建新键，重新分封
        attrs['__mappings__'] = mappings  # 保存属性和列的映射关系,划分个子部分归拢全部参数类型的属性,保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey  # 主键属性名,主键只可能有一个
        attrs['__fields__'] = fields  # 除主键外的属性名
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (
        tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        # 类似 insert into `users` (`email`,`passwd`,`name`, `id`) values (?,?,?,?)
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (
        tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        #即'update `blogs` set `user_id`=?, `user_name`=?, `user_image`=?, `name`=?, `summary`=?, `content`=?, `created_at`=? where `id`=?'
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)#返回的是类实例，类似于类产生实例那样，然后该实例调用类的init方法，这个类实例也就是init里的self
        #总结即 将 原本User类中的attrs重新铸造了一遍

class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):#拿到User实例传过来的参数值
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)#拿到User实例传过来的参数值
        if value is None:#若User实例没有设置某个列的值则取默认值
            field = self.__mappings__[key]#拿到类对象中存储的对应列对象索引,比如 name 为 StringFeild对象索引
            if field.default is not None:#经由该对象索引拿到预先设置的该列的默认值并设置好
                value = field.default() if callable(field.default) else field.default#默认值有可能是可调用的对象
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)


