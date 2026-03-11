from core.services.town_mood_engine import apply_event, mood_label


class TestMoodLabel:
    def test_negative_mood_miserable(self):
        assert mood_label(-50) == "miserable"

    def test_negative_mood_sad(self):
        assert mood_label(-15) == "sad"

    def test_zero_mood_neutral(self):
        assert mood_label(0) == "neutral"

    def test_positive_mood_happy(self):
        assert mood_label(15) == "happy"

    def test_high_mood_elated(self):
        assert mood_label(40) == "elated"


class TestApplyEvent:
    def test_conversation_completed_base(self):
        energy, mood = apply_event("conversation_completed", energy=80, mood=0, traits="")
        assert energy == 75  # -5
        assert mood == 5  # +5

    def test_conversation_completed_introvert(self):
        energy, mood = apply_event("conversation_completed", energy=80, mood=0, traits="introvert")
        assert energy == 70  # -10
        assert mood == 3  # +3

    def test_conversation_completed_extrovert(self):
        energy, mood = apply_event("conversation_completed", energy=80, mood=0, traits="extrovert")
        assert energy == 78  # -2
        assert mood == 8  # +8

    def test_solitary_activity_base(self):
        energy, mood = apply_event("solitary_activity", energy=50, mood=0, traits="")
        assert energy == 53  # +3
        assert mood == 2  # +2

    def test_solitary_activity_introvert(self):
        energy, mood = apply_event("solitary_activity", energy=50, mood=0, traits="introvert")
        assert energy == 55  # +5
        assert mood == 5  # +5

    def test_solitary_activity_extrovert(self):
        energy, mood = apply_event("solitary_activity", energy=50, mood=0, traits="extrovert")
        assert energy == 52  # +2
        assert mood == -2  # -2

    def test_arrived_new_location_base(self):
        energy, mood = apply_event("arrived_new_location", energy=80, mood=0, traits="")
        assert energy == 78  # -2
        assert mood == 0

    def test_arrived_new_location_extrovert(self):
        energy, mood = apply_event("arrived_new_location", energy=80, mood=0, traits="extrovert")
        assert energy == 78  # -2
        assert mood == 3  # +3

    def test_sleep_resets_energy(self):
        energy, mood = apply_event("sleep", energy=20, mood=-10, traits="")
        assert energy == 100
        assert mood == -10  # mood unchanged

    def test_energy_clamped_to_0_100(self):
        energy, mood = apply_event("conversation_completed", energy=2, mood=0, traits="introvert")
        assert energy == 0  # clamped, not negative

    def test_mood_clamped_to_negative_50_positive_50(self):
        energy, mood = apply_event("conversation_completed", energy=80, mood=48, traits="extrovert")
        assert mood == 50  # clamped

    def test_unknown_event_no_change(self):
        energy, mood = apply_event("unknown_event", energy=80, mood=10, traits="")
        assert energy == 80
        assert mood == 10
