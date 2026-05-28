from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有 SQLAlchemy ORM 模型的基类。

    所有模型都继承这个类，因此 MVP 启动时调用 `Base.metadata.create_all()`
    可以发现并创建所有已注册的数据表。
    """
