import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import app as application


NOW = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def event(kind, index, age_minutes=10, points=0, retro_points=0):
    timestamp = (NOW - timedelta(minutes=age_minutes)).isoformat()
    return {
        "type": kind, "dedupe_key": f"{kind}:{index}", "username": "Player", "avatar": "/avatar.png",
        "unlock_time_iso" if kind == "achievement" else "awarded_at": timestamp,
        "points": points, "retro_points": retro_points,
    }


class CatchupInterruptTests(unittest.TestCase):
    def test_five_old_interrupts_remain_individual(self):
        items = [event("achievement", i, points=10) for i in range(5)]
        self.assertEqual(application.condense_stale_interrupts(items, NOW), items)

    def test_six_old_interrupts_become_one_summary(self):
        items = [event("achievement", i, points=10, retro_points=15) for i in range(6)]
        result = application.condense_stale_interrupts(items, NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "catchup")
        self.assertEqual(result[0]["achievement_count"], 6)
        self.assertEqual(result[0]["points"], 60)
        self.assertEqual(result[0]["retro_points"], 90)

    def test_only_old_events_are_condensed_and_awards_are_not_points(self):
        items = [event("achievement", i, points=40, retro_points=60) for i in range(4)]
        items += [event("beaten", 1, points=999), event("mastery", 1, points=999)]
        fresh = event("achievement", 99, age_minutes=2, points=5)
        items.append(fresh)
        result = application.condense_stale_interrupts(items, NOW)
        self.assertEqual([item["type"] for item in result], ["catchup", "achievement"])
        self.assertIs(result[1], fresh)
        self.assertEqual(result[0]["points"], 160)
        self.assertEqual(result[0]["retro_points"], 240)
        self.assertEqual(result[0]["beaten_count"], 1)
        self.assertEqual(result[0]["mastery_count"], 1)

    def test_missing_timestamp_stays_individual(self):
        items = [event("achievement", i) for i in range(6)]
        items.append({"type": "achievement", "dedupe_key": "missing", "username": "Player"})
        result = application.condense_stale_interrupts(items, NOW)
        self.assertEqual([item["type"] for item in result], ["catchup", "achievement"])


class CatchupPollTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_sends_one_catchup_interrupt_instead_of_six(self):
        async def publish_old_events(*_args):
            for index in range(6):
                old = event("achievement", index, points=20)
                old["unlock_time_iso"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                await application.publish_display_event(old)

        with (
            patch.object(application.db, "next_tracked_user_to_poll", return_value={"ra_username": "Player"}),
            patch.object(application.db, "mark_tracked_user_polled") as mark,
            patch.object(application, "process_achievement_unlocks_for_user", new=AsyncMock(side_effect=publish_old_events)),
            patch.object(application, "process_game_awards_for_user", new=AsyncMock()),
            patch.object(application.macos_notification_service, "notify_event", new=AsyncMock(return_value=False)),
            patch.object(application, "broadcast_display_event") as broadcast,
        ):
            await application.poll_for_new_achievements()
        mark.assert_called_once_with("Player")
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args[0]["type"], "catchup")
        self.assertEqual(broadcast.call_args.args[0]["points"], 120)
