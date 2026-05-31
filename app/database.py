from sqlalchemy import create_engine, Column, String, Boolean, Float, Integer, DateTime, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Database URL ─────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://apex_user:apex_pass@localhost:5432/apex_db"
)

# ─── Engine ───────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── DB Table: Events ─────────────────────────────────────────
class EventDB(Base):
    __tablename__ = "events"

    event_id     = Column(String, primary_key=True, index=True)
    store_id     = Column(String, index=True, nullable=False)
    camera_id    = Column(String, nullable=False)
    visitor_id   = Column(String, index=True, nullable=False)
    event_type   = Column(String, nullable=False)
    timestamp    = Column(DateTime(timezone=True), nullable=False, index=True)
    zone_id      = Column(String, nullable=True)
    dwell_ms     = Column(Integer, default=0)
    is_staff     = Column(Boolean, default=False)
    confidence   = Column(Float, nullable=False)
    metadata_    = Column(JSON, default={})


# ─── DB Table: POS Transactions ───────────────────────────────
class TransactionDB(Base):
    __tablename__ = "pos_transactions"

    transaction_id  = Column(String, primary_key=True, index=True)
    store_id        = Column(String, index=True, nullable=False)
    timestamp       = Column(DateTime(timezone=True), nullable=False, index=True)
    basket_value    = Column(Float, nullable=False)


# ─── Create Tables ────────────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created")


# ─── Dependency: Get DB Session ───────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()