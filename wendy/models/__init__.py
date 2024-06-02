from tortoise import models, fields


class Deploy(models.Model):
    id = fields.IntField(pk=True)
    content = fields.JSONField()
    status = fields.CharField(max_length=32)

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
