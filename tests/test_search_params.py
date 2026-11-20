import pytest
from pydantic import ValidationError

from auction_api.types.search import CurrentSearchParams, HistorySearchParams


@pytest.mark.parametrize("model", [CurrentSearchParams, HistorySearchParams])
def test_search_params_keep_cylinder_list(model):
    params = model(site="1", cylinders=[4, 6])
    dumped = params.model_dump(exclude_none=True)

    assert dumped["cylinders"] == [4, 6]


@pytest.mark.parametrize("model", [CurrentSearchParams, HistorySearchParams])
def test_search_params_omit_empty_cylinders(model):
    dumped = model(site="1").model_dump(exclude_none=True)

    assert "cylinders" not in dumped


@pytest.mark.parametrize("model", [CurrentSearchParams, HistorySearchParams])
def test_search_params_reject_non_integer_cylinders(model):
    with pytest.raises(ValidationError):
        model(site="1", cylinders=["six"])
