
import orm
from models import User, Blog, Comment

async def test():
    await orm.create_pool(user='root', password='123456', db='awesome',loop=loop)

    u = User(name='Test', email='test@example.com', passwd='1234567890', image='about:blank')

    await u.save()

module_name = 'handlers.py'
n = module_name.rfind('.')
name = module_name[n+1:]
mod2 = __import__(module_name[:n],globals(),locals(),[name])
# mod = getattr(__import__(module_name[:n],globals(),locals(),[name]),name)
print(dir(mod2))
# app=1
# add_routes(app, 'handlers.py')


# loop = asyncio.get_event_loop()
# app = web.Application(loop=loop)
# handOne = RequestHandler(app,handerOne)
# handerOne()

# path1 = os.path.abspath(__file__)
# path2 = os.path.dirname(os.path.abspath(__file__))
# path = os.path.join(os.path.dirname(os.path.abspath(__file__)),'static')
# print(path1)
# print(path2)
# print(path)