from datetime import datetime, timedelta
import random
import math

# Keeps time moving forward across the session
last_time = None


def _box_muller_gaussian(mean: float, std: float) -> float:
    """
    Generates a number from a bell curve (Gaussian distribution).
    Most values land near the mean, rare values land far from it.
    """
    u1 = max(random.random(), 1e-10)
    u2 = random.random()
    z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
    return mean + std * z


def seed_last_time(timestamp_str: str):
    """
    Called once at startup by run_pipeline to sync last_time with the
    most recent transaction already in the DB. Prevents time going
    backwards after a server restart.
    """
    global last_time
    if last_time is not None:
        return  # already seeded this session, don't overwrite
    try:
        last_time = datetime.strptime(timestamp_str, "%A, %d %B %Y, %I:%M %p")
    except Exception:
        pass  # if parsing fails, get_current_time will seed from now below


def get_current_time(inject_fraud: bool = False) -> str:
    """
    Generates the next transaction timestamp.

    Safe window: 08:00 → 23:59
    Outside window = risk signal.

    Hour selection:
      inject_fraud=True  → forces 1–6am (outside window, strong signal)
      8% chance          → forces 0–6am (natural noise, outside window)
      otherwise          → Gaussian centred at 2pm, std=3
                           explicitly clamped to 08:00–23:59 window
    """
    global last_time

    if last_time is None:
        # Fallback: no DB seed available, start from current real time
        last_time = datetime.now().replace(second=0, microsecond=0)

    # time always moves forward
    if random.random() < 0.80:
        gap = timedelta(minutes=random.randint(5, 180))
    else:
        gap = timedelta(
            days=1,
            hours=random.randint(0, 4),
            minutes=random.randint(0, 59),
        )

    new_time = last_time + gap

    if inject_fraud:
        # force outside window — 1–6am
        new_hour   = random.randint(1, 6)
        new_minute = random.randint(0, 59)

    elif random.random() < 0.08:
        # natural noise — occasional outside-window transaction
        new_hour   = random.randint(0, 6)
        new_minute = random.randint(0, 59)

    else:
        # NORMAL: Gaussian centred at 2pm, clamped to 08:00–23:59
        raw      = _box_muller_gaussian(mean=14, std=3)
        new_hour = int(max(8, min(23, round(raw))))
        new_minute = random.randint(0, 59)

    new_time   = new_time.replace(hour=new_hour, minute=new_minute)
    last_time  = new_time
    return new_time.strftime("%A, %d %B %Y, %I:%M %p")