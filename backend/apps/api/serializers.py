from rest_framework import serializers


AGGREGATE_QUANTITY_MAX_DIGITS = 20


class ItemProgramSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class TherapeuticClassSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()


class WarehouseStockItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    kode_barang = serializers.CharField(allow_blank=True)
    nama_barang = serializers.CharField()
    kategori = serializers.CharField()
    satuan = serializers.CharField()
    is_program_item = serializers.BooleanField()
    program = ItemProgramSerializer(allow_null=True)
    therapeutic_classes = TherapeuticClassSerializer(many=True)
    minimum_stock = serializers.DecimalField(max_digits=12, decimal_places=2)
    physical_quantity = serializers.DecimalField(
        max_digits=AGGREGATE_QUANTITY_MAX_DIGITS,
        decimal_places=2,
    )
    reserved_quantity = serializers.DecimalField(
        max_digits=AGGREGATE_QUANTITY_MAX_DIGITS,
        decimal_places=2,
    )
    available_quantity = serializers.DecimalField(
        max_digits=AGGREGATE_QUANTITY_MAX_DIGITS,
        decimal_places=2,
    )
    is_low_stock = serializers.BooleanField()
    expired_batch_count = serializers.IntegerField()
    expiring_batch_count = serializers.IntegerField()


class WarehouseStockResponseSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    cache_ttl_seconds = serializers.IntegerField()
    period = serializers.DictField()
    count = serializers.IntegerField()
    results = WarehouseStockItemSerializer(many=True)


class PuskesmasStockItemSerializer(serializers.Serializer):
    facility_id = serializers.IntegerField()
    facility_name = serializers.CharField()
    item_id = serializers.IntegerField()
    kode_barang = serializers.CharField(allow_blank=True)
    nama_barang = serializers.CharField()
    kategori = serializers.CharField()
    satuan = serializers.CharField()
    is_program_item = serializers.BooleanField()
    program = ItemProgramSerializer(allow_null=True)
    therapeutic_classes = TherapeuticClassSerializer(many=True)
    stock_current = serializers.IntegerField()
    minimum_stock = serializers.IntegerField()
    is_below_threshold = serializers.BooleanField()
    base_month = serializers.IntegerField()
    base_month_label = serializers.CharField()
    base_year = serializers.IntegerField()
    receipt_adjustment = serializers.IntegerField()
    consumption_adjustment = serializers.IntegerField()


class PuskesmasStockResponseSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    cache_ttl_seconds = serializers.IntegerField()
    period = serializers.DictField()
    count = serializers.IntegerField()
    results = PuskesmasStockItemSerializer(many=True)


class ErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
