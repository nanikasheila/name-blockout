def test_full_speed_does_nothing_off_windows(monkeypatch):
    import subprocess

    from name_blockout.cli import full_speed

    monkeypatch.setattr("sys.platform", "linux")
    child = subprocess.Popen(["true"])
    assert full_speed(child) is False
    child.wait()
