from rest_framework import serializers


class WarehouseStockItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    kode_barang = serializers.CharField(allow_blank=True)
    nama_barang = serializers.CharField()
    kategori = serializers.CharField()
    satuan = serializers.CharField()
    minimum_stock = serializers.DecimalField(max_digits=12, decimal_places=2)
    physical_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    reserved_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    available_quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
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
    kode_barang = serializers.CharField(allow_blank=True)
    nama_barang = serializers.CharField()
    kategori = serializers.CharField()
    satuan = serializers.CharField()
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
