from rest_framework import serializers

# pylint: disable=abstract-method
class AvailableTimespanSerializer(serializers.Serializer):
    """ Serializer not tied to TutorAvailability model that indicates a span of time a
        tutor is available.
        We use this instead of TutorAvailabilitySerializer when we need to combined adjacent TutorAvailability
        objects into larger timespans
    """

    tutor = serializers.IntegerField()
    counselor = serializers.IntegerField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    location = serializers.IntegerField()
