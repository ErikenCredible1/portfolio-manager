from portfolio_app import select_tax_harvest_candidates


def test_selects_all_when_everything_fits():
    positions = [("A", -1000.0), ("B", -1500.0), ("C", -200.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == {"A", "B", "C"}  # total 2700, all fit


def test_skips_a_loss_that_would_overshoot_but_keeps_checking_smaller_ones():
    # A (2000, largest) is taken first. B (1800) would push the total to 3800 and is
    # skipped. C (900) is checked next and still fits (2000 + 900 = 2900) -- proving the
    # algorithm keeps looking past the first miss instead of stopping.
    positions = [("A", -2000.0), ("B", -1800.0), ("C", -900.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == {"A", "C"}


def test_ignores_gains():
    positions = [("A", -500.0), ("B", 900.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == {"A"}


def test_returns_empty_set_when_target_is_zero():
    positions = [("A", -500.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=0)
    assert selected == set()


def test_returns_empty_set_with_no_losers():
    positions = [("A", 500.0), ("B", 200.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == set()
