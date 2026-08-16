from sqlalchemy.orm import DeclarativeBase


# Separate declarative base for the user-service database, kept distinct from
# the catalog base so the two schemas have independent metadata (e.g. both can
# define a `brand` table without colliding).
class Base(DeclarativeBase):
    pass
