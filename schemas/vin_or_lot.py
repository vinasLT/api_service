from request_schemas.lot import SiteIn


class VinOrLotIn(SiteIn):
    vin_or_lot: str

    @classmethod
    def validate_site(cls, v):
        return v


