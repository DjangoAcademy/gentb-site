# -*- coding: utf-8 -*-
# Generated by Django 1.11.9 on 2019-01-25 20:34
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mutations', '0015_auto_20190125_1512'),
    ]

    operations = [
        migrations.AddField(
            model_name='drug',
            name='priority',
            field=models.IntegerField(default=0, help_text=b'Priority of drug in regimen'),
        ),
    ]
