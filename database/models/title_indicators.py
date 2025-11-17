from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from database.models import Base


class TitleIndicators(Base):
    __tablename__ = "title_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)

    site: Mapped[str] = mapped_column(String(16), nullable=False)
    title_name: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=True)
