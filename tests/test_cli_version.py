import sdwan_automation


def test_installed_version_returns_not_installed_for_unknown_package():
    assert (
        sdwan_automation._installed_version("definitely-not-a-real-python-package-name")
        == "not installed"
    )
