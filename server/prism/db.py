from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from prism.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
SessionLocal = sessionmaker(bind=engine)
