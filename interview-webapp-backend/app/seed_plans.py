"""
Idempotent subscription plan seeder.
Called from init_db() at startup — safe to call multiple times.
"""
from app.models.subscription_plan import SubscriptionPlan

PLANS = [
    {"plan_name": "Basic", "max_admins": 1, "max_recruiters": 5, "max_interviews": 25},
    {"plan_name": "Professional", "max_admins": 3, "max_recruiters": 15, "max_interviews": 100},
    {"plan_name": "Enterprise", "max_admins": 10, "max_recruiters": 50, "max_interviews": 500},
]


async def seed_subscription_plans():
    for p in PLANS:
        existing = await SubscriptionPlan.find_one(
            {"plan_name": p["plan_name"]}
        )
        if not existing:
            plan = SubscriptionPlan(**p)
            await plan.insert()
