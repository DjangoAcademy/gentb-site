#
# Copyright (C) 2017  Dr. Maha Farhat
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Mixins specially for the maps app
"""

from operator import or_, and_
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.query import Q, QuerySet
from django.template.response import SimpleTemplateResponse
from django.views.decorators.cache import cache_page
from django.views.generic import View

from django.http import JsonResponse, HttpResponse
from django.conf import settings

from .utils import Jdict

#Inherit from the parent class DjangoJsonEncoder and modify the default method to create our own encoder
#ParentClass: https://github.com/django/django/blob/master/django/core/serializers/json.py

class DjangoJSONEncoder2(DjangoJSONEncoder):
    """A json encoder to deal with the python objects we may want to encode"""
    def default(self, obj):
        """Add the ability to deal with timedelta"""
        if isinstance(obj, timedelta):
            args = ('days', 'seconds', 'microseconds')
            # So if we get a time-delta object return a dictionary with
            # type and a list of the day, second, microseconds
            return {'__type__': 'datetime.timedelta',
                    'args': [getattr(obj, arg) for arg in args]}
        if isinstance(obj, QuerySet):
            return [item for item in obj]
        return DjangoJSONEncoder.default(self, obj)

#Inherit from the parent class View and add Caching
#ParentClass: https://github.com/django/django/blob/master/django/views/generic/base.py

class JsonView(View):
    """Quickly serve a python data structure as json"""
    cache_timeout = 5 * 60 * 60 * 24

    def get_cache_timeout(self):
        """Return the amount of time this data should be cached for"""
        return self.cache_timeout

    def dispatch(self, *args, **kwargs):
        """When Get or Post is called, convert data into json"""
        def _dispatch(request, *args, **kwargs): # pylint: disable=unused-argument
            # The self.get_context_data is what each view will change
            # in views.py depending on the kind of data/how you want
            # to visualize this data
            context = self.get_context_data(**kwargs)
            return self.render_to_response(context)

        # Wrapping cache_page with the call to dispatch
        # (saying the view that dispatch returns should be cached)
        # The caching is implemented for performance boost
        return cache_page(self.get_cache_timeout())(_dispatch)(*args, **kwargs)

    def render_to_response(self, context):
        """Return an actual json response, except where 'html' is set to 1"""
        if self.request.GET.get('html', False):
            return SimpleTemplateResponse('maps/json-debug.html', context)
        return JsonResponse(context, encoder=DjangoJSONEncoder2)


class DataSlicerMixin(object):
    """
    Provide a way to slice up a given model based on inputs.
    """
    filters = {}
    required = []
    order = []
    values = []

    def get_model(self):
        """Return the basic model to slice"""
        try:
            return self.model
        except:
            raise NotImplementedError("You must provide a model to slice.")

    def get_filters(self, without=None):
        """Gets the filter applied to the queryset for this slice."""
        for (key, filtrs) in self.filters.items():
            if key not in self.request.GET and key not in self.required:
                continue
            yield reduce(or_, self.get_filter_or(key, filtrs, without), Q())

    def get_filter_or(self, key, filtrs, without=None):
        """Allow alternate filters to be used, useful when multiple"""
        for filtr in (as_set(filtrs) ^ (as_set(without) & as_set(filtrs))):
            yield self.get_filter_value(key, filtr)

    def get_filter_value(self, key, filtr):
        """Get the specific value, either a list or a single value"""
        value = self.request.GET.get(key, '')
        if filtr.endswith('__in'):
            value = self.request.GET.getlist(key, [])
        return Q(**{filtr: value})

    def get_queryset(self, without=None):
        """Applies any filters from the request query to the given model"""
        qset = self.get_model().objects.all()
        if self.order:
            qset = qset.order_by(*self.order)
        return qset.filter(reduce(and_, self.get_filters(without), Q()))

    def get_data(self, without=None):
        """Returns the queryset with the default values"""
        qset = self.get_queryset(without=without)
        if self.values:
            vals = [v for v in self.values if v != without]
            qset = qset.values(*vals)
        return qset

    def get_list(self, qs, column, *cols):
        """Returns a flat list for this column"""
        if cols:
            qs = qs.values_list(column, *cols)
        else:
            qs = qs.values_list(column, flat=True)
        return qs.distinct().order_by(column)

def as_set(val):
    """
    Turn the value into a set, three outputs are possible:

        None -> Empty set set()
        list -> Set of items in the list set(list)
        item -> Set of one item set([item])
    """
    if val is None:
        return set()
    return set(val) if isinstance(val, (tuple, list)) else set([val])

class DataTableMixin(object):
    """
    Return context rendered as a Json output for the DataTables plugin.
    """
    search_fields = []

    def get(self, request, pk=None):
        """
        Overload the ListView's get and replace with datatable getter.
        """
        super(DataTableMixin, self).get(request)
        data = super(DataTableMixin, self).get_context_data()
        dt_settings = Jdict(request.GET)
        if 'draw' not in dt_settings:
            return JsonResponse({'error': "Please use with dataTables."})
        try:
            draw = int(dt_settings['draw'])
            aset = data['object_list']
            qset, count = self.process_datatable(aset, **dt_settings)
            if dt_settings.get('pks', False):
                return JsonResponse({
                    'data': qset.values_list('pk', flat=True),
                })
            return JsonResponse({
                'draw': draw,
                'recordsTotal': aset.count(),
                'recordsFiltered': count,
                'data': self.prep_data(qset, dt_settings.get('columns', [])),
            })
        except Exception as err:
            return JsonResponse({'error': str(err)})

    def prep_data(self, qset, columns):
        """
        Prepare the full data set.
        """
        db_columns = [self.column_to_django(col) for col in columns]
        return [self.prep_item(item, columns) for item in qset.values(*db_columns)]

    def prep_item(self, obj, columns):
        """
        Prepare this item for output using the requested columns.
        """
        return obj

    def column_to_django(self, column, db=True):
        """We calculate the column's django address,
        
        If db is True, then this must return the database field, if false
        then we must return the attribute getter.
        """
        return column['data']

    def process_datatable(self, qset, columns=(), order=(), search=None, start=0, length=-1, **junk):
        """
        Takes the options as shown in https://datatables.net/manual/server-side
        and returns the query set as modified by the options.
        """
        query = Q()
        for column in columns:
            column['django'] = self.column_to_django(column)
            col_search = column.get('search', None)
            if col_search is not None and 'value' in col_search and col_search['value']:
                query |= Q(**{column['django'] + '__icontains': col_search['value']})

        if search is not None and 'value' in search and search['value']:
            for col in self.search_fields:
                query |= Q(**{col + '__icontains': search['value']})

        qset = qset.filter(query)

        # Do this before ordering, because we have a BUG in jsonb
        count = qset.count()

        ordering = []
        for order_col in order:
            column = columns[int(order_col['column'])]['django']
            if order_col['dir'][0] == 'd':
                column = '-' + column
            ordering.append(column)
        if ordering:
            qset = qset.order_by(*ordering)

        if int(length) > 0:
            return qset[int(start):int(start) + int(length)], count
        return qset, count
