""" Serializers for validating the data we use to interface with Magento
"""
from rest_framework import serializers


class MagentoPurchasePayloadSerializer(serializers.Serializer):
    """ Spec for payload: https://www.notion.so/Magento-Integration-d33a760d0a244db8a75bd492b5277d1b
        Note that this serializer is meant to work with data passed in a single object of the items array
        in full magento payload at link above (i.e. view must extract the nested data needed)
    """

    created_at = serializers.DateTimeField()
    customer_email = serializers.CharField()  # Person who made purchase
