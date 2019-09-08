#
# fxcmpy -- A Python Wrapper Class for the
# RESTful API as provided by FXCM Forex Capital Markets Ltd.
#
# The codes contained herein come without warranties or representations,
# to the extent permitted by applicable law.
#
# Read the RISK DISCLAIMER carefully.
#
# (c) FXCM Forex Capital Markets Ltd.
#

import requests
from socketIO_client import SocketIO
from socketIO_client.exceptions import ConnectionError
from threading import Thread
import json
import pandas as pd
import sys
import time
import datetime as dt
import configparser
import logging

import fxcmpy.fxcmpy_instruments as fxcmpy_instruments 
from fxcmpy.fxcmpy_closed_position import fxcmpy_closed_position
from fxcmpy.fxcmpy_open_position import fxcmpy_open_position
from fxcmpy.fxcmpy_oco_order import fxcmpy_oco_order
from fxcmpy.fxcmpy_order import fxcmpy_order

from urllib.parse import unquote


class ServerError(Exception):
    pass


class fxcmpy(object):
    """ A wrapper class for the FXCM API. """

    # Class attributes

    # auth_url = 'https://www-beta2.fxcorporate.com'
    # trading_url = 'https://api-demo.fxcm.com'
    # port = 443
    models = ['Offer', 'Account', 'Order', 'OpenPosition', 'ClosedPosition',
              'Summary', 'Properties', 'LeverageProfile']
    PERIODS = ['m1', 'm5', 'm15', 'm30', 'H1', 'H2', 'H3', 'H4', 'H6', 'H8',
               'D1', 'W1', 'M1']
    CANDLES_COLUMNS = ['date', 'bidopen', 'bidclose', 'bidhigh', 'bidlow',
                       'askopen', 'askclose', 'askhigh', 'asklow', 'tickqty']
    CANDLES_COLUMNS_ASK = ['date', 'askopen', 'askclose', 'askhigh', 'asklow']
    CANDLES_COLUMNS_BID = ['date', 'bidopen', 'bidclose', 'bidhigh', 'bidlow']
    LOG_LEVELS = {'error': 40, 'warn': 30, 'info': 20, 'debug': 10}
    LOG_FORMAT = '|%(levelname)s|%(asctime)s|%(message)s'
    PROXY_TYPES = ['http', 'socks4', 'socks5']
    SERVERS = {
        'demo': 'https://api-demo.fxcm.com',
        'real': 'https://api.fxcm.com',
        'demo2': 'https://api-demo.fuhuisupport.com',
        'real2': 'https://api.fuhuisupport.com'
    }
    port = 443

    debug = False

    def __init__(self, access_token='', config_file='',
                 log_file=None, log_level='', server='demo',
                 proxy_url=None, proxy_port=None, proxy_type=None):
        """ Constructor.

        Arguments:

        access_token: string (default: ''),
            an access token for your FXCM account. To create an access token
            visit https://tradingstation.fxcm.com/
        config_file: string (default: ''),
            path of an optional configuration file, fxcm tries to read all
            other parameter which are not given from that file. The file must
            be readable by configparser.
        log_file: string (default: None),
            path of an optional log file. If not given (and not found in the
            optional configuration file), log messages are printed to stdout.
        log_level: string (default: 'warn'),
            the log level. Must be one of 'error', 'warn', 'info' or 'debug'.
            If not given (and not found in the optional configuration file),
            'warn' is used.
        server: one of 'demo' or 'real' (default: 'demo'),
            wheter to use the fxcm demo or real trading server.
        proxy_url, string (default: None):
            if given (or found in the optional configuration file), the url is 
            used for pproxy.
        proxy_port, integer (default: None):
            if proxy_url is given (or found in the optional configuration file),
            this is the port of the proxy server.
        proxy_type, one of 'http', 'socks4', 'socks5' or None (default: 'http'),
            if proxy_url is given (or found in the optional configuration file),
            this is the type of the proxy server.

        """

        config = configparser.SafeConfigParser()
        found_config_file = config.read(config_file)
        if config_file:
            if len(found_config_file) == 0:
                raise IOError("Can not open config file: {0}"
                    .format(config_file))
            if 'FXCM' not in config.sections():
                raise ValueError("Can not find section [FXCM] in {0}"
                    .format(config_file))
        else:
            config.add_section('FXCM')
        
        if not log_level:
            log_level = config['FXCM'].get('log_level','warn')
        log_level = log_level.strip('"').strip("'")
        if log_level in self.LOG_LEVELS:
            log_level = self.LOG_LEVELS[log_level]
        else:
            raise ValueError("log_level must be one of {0}"
                .format(self.LOG_LEVELS.keys()))
        
        if not log_file:
            log_file = config['FXCM'].get('log_file')
        if log_file:
            log_file = log_file.strip('"').strip("'")
            if config_file == log_file:
                raise Exception("config_file and log_file must be different")
            logging.basicConfig(filename=log_file, level=log_level,
                                format=self.LOG_FORMAT)
        else:
            logging.basicConfig(level=log_level, format=self.LOG_FORMAT)
        self.logger = logging.getLogger('FXCM')
        
        if not server:
            server = config['FXCM'].get('server','demo')
        server = server.strip('"').strip("'")
        if server in self.SERVERS:
            self.trading_url = self.SERVERS[server]
        else:
            raise ValueError("server must be one of {0}"
                .format(self.SERVERS.keys()))
        
        self.access_token = access_token
        if not self.access_token:
            self.access_token = config['FXCM'].get('access_token')
        if not self.access_token:
            raise ValueError("access_token not provided")
        self.access_token = self.access_token.strip('"').strip("'")
        if len(self.access_token) != 40:
            raise ValueError("access_token must have a length of 40 characters")
        
        if not proxy_url:
            proxy_url = config['FXCM'].get('proxy_url')
        if proxy_url:
            proxy_url = proxy_url.strip('"').strip("'")
            if not proxy_port:
                proxy_port = config['FXCM'].get('proxy_port')
            if not proxy_port:
                raise ValueError("proxy_port not provided")
            try:
                proxy_port = int(proxy_port)
            except ValueError:
                pass
            if not isinstance(proxy_port,int):
                raise ValueError("proxy_port must be an integer")
            if not 1 <= proxy_port <= 65535:
                raise ValueError("proxy_port must be between 1 and 65535")
            if not proxy_type:
                proxy_type = config['FXCM'].get('proxy_type','http')
            proxy_type = proxy_type.strip('"').strip("'")
            if proxy_type not in self.PROXY_TYPES:
                raise ValueError("proxy_type must be one of {0}"
                                 .format(", ".join(str(t) for t in self.PROXY_TYPES)))
            sec_proxy_type = 'https' if proxy_type == 'http' else proxy_type
            self.proxies = {
                'https': "{0}://{1}:{2}"
                    .format(sec_proxy_type, proxy_url, proxy_port),
                'http': "{0}://{1}:{2}"
                    .format(proxy_type, proxy_url, proxy_port)
            }
        else:
            self.proxies = {}

        self.socket = None
        self.socket_thread = None
        self.orders_set = False
        self.oco_orders_set = False
        self.offers_set = False
        self.positions_set = False
        self.request_header = None
        self.default_account = None
        self.instruments = None
        self.number_update_requests = 0
        self.prices = dict()
        self.account_ids = set()
        self.orders = dict()
        self.old_orders = dict()
        self.offers = dict()
        self.open_pos = dict()
        self.closed_pos = dict()
        self.oco_orders = dict()
        self.add_callbacks = dict()
        self.connection_status = 'unset'
        self.max_prices = 10000
        self.connect()

        count = 0
        while ((self.connection_status == 'pending' or 
                self.connection_status == 'unset') and count < 50):
            count += 1
            time.sleep(1)

        if self.connection_status == 'pending' and count == 50:
            raise ServerError('Can not find FXCM Server.')
        elif self.connection_status == 'aborted':
            raise ServerError('Can not connect to FXCM Server.')

        self.__collect_account_ids__()
        self.default_account = self.account_ids[0]
        msg = 'Default account set to %s, to change use set_default_account().'
        self.logger.warning(msg % self.default_account)
        self.__collect_orders__()
        self.__collect_oco_orders__()
        self.__collect_offers__()
        self.__collect_positions__()
        self.instruments = self.get_instruments()
        self.subscribe_data_model('Order')
        self.subscribe_data_model('OpenPosition')
        self.subscribe_data_model('ClosedPosition')
        self.__disconnected__ = False

    def close(self):
        self.__disconnected__ = True
        if self.is_connected():
            self.socket.disconnect()
            self.socket_thread.join()
            time.sleep(2)
        self.socket = None
        self.request_header = None
        self.default_account = None
        self.instruments = None
        self.prices = dict()
        self.account_ids = set()
        self.orders = dict()
        self.old_orders = dict()
        self.offers = dict()
        self.open_pos = dict()
        self.closed_pos = dict()
        self.oco_orders = dict()
        self.add_callbacks = dict()
        self.connection_status = 'unset'

    def connect(self):
        """ Connect to the FXCM server."""
        self.connection_status = 'pending'
        self.logger.info('Connecting FXCM Server')

        self.socket_thread = Thread(target=self.__connect__)
        self.socket_thread.start()

    def is_connected(self):
        """ Return True if socket connection is established and False else."""

        if (self.socket is not None and self.socket.connected and
                self.socket_thread.is_alive()):
            return True
        else:
            return False

    def get_default_account(self):
        """ Return the default account id."""
        return self.default_account

    def set_default_account(self, account_id):
        """" Set the default account id to account_id."""
        if account_id not in self.account_ids:
            raise ValueError("Unknown account id")
        else:
            self.default_account = account_id

    def get_max_prices(self):
        """ Return the max length of the market price tables."""
        return self.max_prices

    def set_max_prices(self, max_prices):
        """ Set the max lenght of the market price tables.
        
        Arguments:

        max_prices, int or None (Default 10000): The max length of the price 
            tables, if set to None, the price tables are unlimited.

        """
        if max_prices is not None:
            try:
                max_prices = int(max_prices)
            except Exception:
                raise TypeError('max_prices must be an integer')
            if max_prices < 1:
                raise ValueError('max_prices must be positive')
        self.max_prices = max_prices

    def get_instruments(self):
        """ Return the tradeable instruments of FXCM as a list."""

        self.logger.debug('Fetching available instruments')

        data = self.__get_instruments_table__()

        if 'data' in data and 'instrument' in data['data']:
            instruments = [ins['symbol'] for ins in data['data']['instrument']]
        else:
            instruments = list()

        return instruments

    def get_model(self, models=None, summary=False):
        """ Return a snapshot of the the specified model(s).

        Arguments:

        models: list,
            list of the required models, entries must be out of
            ['Offer', 'Account', 'Order', 'OpenPosition', 'ClosedPosition',
             'Summary', 'Properties', 'LeverageProfile'].

        Returns:

        The current data of the specified model(s) in a json like manner.

        """

        if models is None:
            models = list()

        if len(models) == 0:
            raise ValueError('Please specify one or more models')
        for model in models:
            if model not in self.models:
                raise ValueError('Models have to be of %s' % self.models)

        data = self.__handle_request__(method='trading/get_model',
                                       params={'models': list(models)})

        total = dict()
        for table in data:
            total[table] = list()
            for dataset in data[table]:
                if 'isTotal' in dataset and dataset['isTotal'] is True:
                    total[table].append(dataset)
                    data[table].remove(dataset)
        if summary:
            return total
        else:
            return data

    def get_open_positions(self, kind='dataframe'):
        """ Return a snapshot of the 'Open Position' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The current data of the 'Open Position' model.

        """
        data = self.get_model(('OpenPosition',))
        open_pos = data['open_positions']
        if kind == 'list':
            return open_pos
        else:
            return pd.DataFrame(open_pos)

    def get_closed_positions(self, kind='dataframe'):
        """ Return a snapshot of the 'Closed Position' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The current data of the 'Closed Position' model.

        """
        data = self.get_model(('ClosedPosition',))
        closed_pos = data['closed_positions']
        if kind == 'list':
            return closed_pos
        else:
            return pd.DataFrame(closed_pos)

    def get_offers(self, kind='dataframe'):
        """ Return a snapshot of the 'Offer' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The current data of the 'Offer' model.

        """
        data = self.get_model(('Offer',))
        offers = data['offers']
        if kind == 'list':
            return offers
        else:
            return pd.DataFrame(offers)

    def get_orders(self, kind='dataframe'):
        """ Return a snapshot of the 'Order' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The current data of the 'Order' model.

        """
        data = self.get_model(('Order',))
        orders = data['orders']
        if kind == 'list':
            return orders
        else:
            return pd.DataFrame(orders)

    def get_summary(self, kind='dataframe'):
        """ Return a snapshot of the 'Summary' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The current data of the 'Summary' model.

        """
        data = self.get_model(('Summary',))
        summary = data['summary']
        if kind == 'list':
            return summary
        else:
            return pd.DataFrame(summary)

    def get_open_positions_summary(self, kind='dataframe'):
        """ Return a summary of the 'Open Position' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The summary of the current data of the 'Open Position' model.

        """
        data = self.get_model(('OpenPosition',), summary=True)
        open_pos = data['open_positions']
        if kind == 'list':
            return open_pos
        else:
            return pd.DataFrame(open_pos)

    def get_closed_positions_summary(self, kind='dataframe'):
        """ Return a summary of the 'Closed Position' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The summary of the current data of the 'Closed Position' model.

        """
        data = self.get_model(('ClosedPosition',), summary=True)
        closed_pos = data['closed_positions']
        if kind == 'list':
            return closed_pos
        else:
            return pd.DataFrame(closed_pos)

    def get_accounts(self, kind='dataframe'):
        """ Return a snapshot of the 'Account' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The current data of the 'Account' model.

        """
        data = self.get_model(('Account',))
        accounts = data['accounts']
        if kind == 'list':
            return accounts
        else:
            return pd.DataFrame(accounts)

    def get_accounts_summary(self, kind='dataframe'):
        """ Return a summary of the 'Account' model.

        Arguments:

        kind: one of 'dataframe' (default) or 'list',
            how to return the data, either as list or as a pandas DataFrame.

        Returns:

        The summary of the current data of the 'Account' model.

        """
        data = self.get_model(('Account',), summary=True)
        accounts = data['accounts']
        if kind == 'list':
            return accounts
        else:
            return pd.DataFrame(accounts)

    def get_account_ids(self):
        """ Return a list of available account ids."""

        return self.account_ids

    def get_order_ids(self):
        """ Return a list of available order ids."""

        return list(self.orders.keys())

    def get_open_trade_ids(self):
        """ Return a list of all available trade ids of open positions."""

        return list(self.open_pos.keys())

    def get_closed_trade_ids(self):
        """ Return a list of all available trade ids of closed positions."""

        return list(self.closed_pos.keys())

    def get_all_trade_ids(self):
        """Returns a list of all available trade ids."""

        ids = set(self.get_open_trade_ids())
        ids = ids.union(set(self.get_closed_trade_ids()))
        ids = list(ids)
        ids.sort()

        return ids

    def get_open_position(self, position_id):
        """ Return the open position with given id.

        Arguments:

        position_id: (integer),
            the id of the position.

        Returns:

        The fxcmpy_open_position object.
        """
        try:
            position_id = int(position_id)
        except:
            self.logger.error('position id must be an integer.')
            raise TypeError('position id must be an integer.')

        if position_id in self.open_pos:
            return self.open_pos[position_id]
        else:
            self.logger.warning('No open position with id %s.' % position_id)
            raise ValueError('No open position with id %s.' % position_id)

    def get_closed_position(self, position_id):
        """ Return the closed position with given id.

        Arguments:

        position_id: (integer),
            the id of the position.

        Returns:

        The fxcmpy_open_position object.
        """
        try:
            position_id = int(position_id)
        except:
            self.logger.error('position id must be an integer.')
            raise TypeError('position id must be an integer.')

        if position_id in self.closed_pos:
            return self.closed_pos[position_id]
        else:
            self.logger.warn('No closed position with given id %s.'
                             % position_id)
            raise ValueError('No closed position with given id %s.'
                             % position_id)

    def get_order(self, order_id):
        """ Returns the order object for a given order id.

        Arguments:

        order_id: (integer),
            the id of the order.

        Returns:

        The fxcmpy_order object.
        """

        if order_id in self.orders:
            return self.orders[order_id]
        elif order_id in self.old_orders:
            return self.old_orders[order_id]
        else:
            raise ValueError('No order with id %s' % order_id)

    def get_oco_order_ids(self):
        """ Return a list of the available oco order ids."""

        return list(self.oco_orders.keys())

    def get_oco_order(self, order_id):
        """ Returns the oco order object for a given order id.

        Arguments:

        order_id: (integer),
            the id of the oco order.

        Returns:

        The fxcmpy_oco_order_object.
        """

        if order_id not in self.oco_orders:
            raise ValueError('No oco order with id %s' % order_id)
        else:
            return self.oco_orders[order_id]

    def get_prices(self, symbol):
        """ Return the prices of a given subscribed instrument.

        Arguments:

        symbol: string,
            the symbol of the instrument as given by get_instruments().

        """

        if symbol in self.prices:
            return self.prices[symbol]
        else:
            return pd.DataFrame(columns=['Bid', 'Ask', 'High', 'Low'])

    def get_last_price(self, symbol):
        """ Return the last prices of a given subscribed instrument.

        Arguments:

        symbol: string,
            the symbol of the instrument as given by get_instruments().

        """

        if symbol in self.prices:
            return self.prices[symbol].iloc[-1]
        else:
            raise ValueError('Symbol %s is not subscripted' % symbol)

    def get_subscribed_symbols(self):
        """ Returns a list of symbols for the subscribed instruments."""

        return list(self.prices.keys())

    def is_subscribed(self, symbol):
        """ Returns True if the instrument is subscribed and False else.

        Arguments:

        symbol:  string,
            the symbol of the instrument in question as given by
            get_instruments().

        """

        return symbol in self.prices

    def subscribe_market_data(self, symbol='', add_callbacks=()):
        """ Stream the prices of an instrument.

        Arguments:

        symbol:  string,
            the symbol of the instrument in question as given by
            get_instruments().

        add_callbacks: list of callables,
            all methods in that list will be called for every incoming dataset
            of the instrument. Such a method has to accept two positional
            arguments, data and dataframe, say. The first should be a json like
            object with the new price data received by the stream and the
            second should be a Pandas DataFrame with the collected price data
            as given by get_prices().

        """

        if symbol == '':
            raise ValueError('No symbol given.')

        self.logger.info('Try to subscribe for %s.' % symbol)

        for func in add_callbacks:
            if not callable(func):
                self.logger.error('Callback method is not callable.')
                raise ValueError('Content of add_callbacks is not callable.')
            else:
                if symbol not in self.add_callbacks:
                    self.add_callbacks[symbol] = dict()
                self.logger.info('Adding callback method %s for symbol %s.'
                                 % (func.__name__, symbol))
                self.add_callbacks[symbol][func.__name__] = func

        params = {'pairs': symbol}
        data = self.__handle_request__(method='subscribe', params=params,
                                       protocol='post')
        if symbol not in self.prices:
            data = data['pairs'][0]
            date = pd.to_datetime(int(data['Updated']), unit='ms')
            self.prices[symbol] = pd.DataFrame([data['Rates'][0:4]],
                                               columns=['Bid', 'Ask', 'High', 'Low'],
                                               index=[date])
        self.socket.on(symbol, self.__on_price_update__)

    def subscribe_data_model(self, model='', add_callbacks=()):
        """ Stream data of a model.

        Arguments:

        model: string,
            the model, must be one of ['Offer', 'Account', 'Order',
            'OpenPosition', 'ClosedPosition', 'Summary', 'Properties',
            'LeverageProfile'].

        add_callbacks: list of callables,
            all methods in that list will be called for every incoming dataset
            of the model. Such a method has to accept two positional
            arguments, data and dataframe, say. The first should be a json like
            object with the new data received by the stream and the second
            should be a Pandas DataFrame with the collected data.

        """
        if model == '':
            raise ValueError('No model given.')

        if model not in ['Offer', 'Account', 'Order', 'OpenPosition',
                         'ClosedPosition', 'Summary']:
            msg = "model must on of 'Offer', 'Account', 'Order',"
            msg += "'OpenPosition', 'ClosedPosition' or 'Summary'"
            raise ValueError(msg)

        self.logger.info('Try to subscribe for %s.' % model)

        for func in add_callbacks:
            if not callable(func):
                self.logger.error('Callback method is not callable.')
                raise ValueError('Content of add_callbacks must be callable.')
            else:
                if model not in self.add_callbacks:
                    self.add_callbacks[model] = dict()
                self.logger.info('Adding callback method %s for model %s.'
                                 % (func.__name__, model))
                self.add_callbacks[model][func.__name__] = func

        params = {'models': model}
        self.__handle_request__(method='trading/subscribe',
                                       params=params, protocol='post')
        if model == 'Order':
            self.socket.on('Order', self.__on_order_update__)
        elif model == 'OpenPosition':
            self.socket.on('OpenPosition', self.__on_open_pos_update__)
        elif model == 'ClosedPosition':
            self.socket.on('ClosedPosition', self.__on_closed_pos_update__)

        else:
            self.socket.on(model, self.__on_model_update__)

    def subscribe_instrument(self, symbol):
        """ Subscribe an instrument so that it appears in the offers table.

        Arguments:

        symbol, string:
            the symbol of the instrument to activate.

        Returns:
            True by success and False else.
        """
        ret = self.__update__instrument_subscription__(symbol, True)
        return ret

    def unsubscribe_instrument(self, symbol):
        """ Unsubscribe an instrument so that it does not appears in the 
        offers table.

        Arguments:

        symbol, string:
            the symbol of the instrument to activate.

        Returns:
            True by success and False else.
        """

        ret = self.__update__instrument_subscription__(symbol, False)
        return ret

    def unsubscribe_market_data(self, symbol=''):
        """ Unsubscribe for instrument prices of the given symbol."""

        if symbol == '':
            raise ValueError('No symbol given.')

        self.logger.info('Try to unsubscribe for %s.' % symbol)

        params = {'pairs': symbol}
        self.__handle_request__(method='unsubscribe', params=params,
                                       protocol='post')

        if symbol in self.prices:
            del self.prices[symbol]
        if symbol in self.add_callbacks:
            del self.add_callbacks[symbol]

    def unsubscribe_data_model(self, model=''):
        """ Unsubscribe for the given model.

        Arguments:

        model: string,
            the model, must be one of ['Offer', 'Account', 'Order',
            'OpenPosition', 'ClosedPosition', 'Summary', 'Properties',
            'LeverageProfile'].

        """

        if model == '':
            raise ValueError('No symbol given.')

        self.logger.info('Try to unsubscribe for %s.' % model)
        if model not in ['Order', 'OpenPosition', 'ClosedPosition']:
            params = {'models': model}
            self.__handle_request__(method='trading/unsubscribe',
                                           params=params, protocol='post')
        else:
            msg = 'Model %s is used by intern routines, cancel unsubscibtion, '
            msg += 'only remove custom callbacks.'
            self.logger.warn(msg % model)

        if model in self.add_callbacks:
            del self.add_callbacks[model]

    def close_all_for_symbol(self, symbol, order_type='AtMarket',
                             time_in_force='GTC', account_id=None):
        """ Close all positions for a given symbol.

        Arguments:

        account_id: string,
            the order's account id.

        symbol: string,
            the trades symbol as given by get_instruments.

        order_type: string (default: 'AtMarket'),
            the type of order execution, one of 'AtMarket' or 'MarketRange'.

        time_in_force: string (default: 'GTC'),
            the time in force of the order execution, must be one of
            'IOC', 'GTC', 'FOK' or 'DAY'.

        account_id: integer (Default None),
            the order's account id. If not given, the default account is used.

        """

        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')
        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        if order_type not in ['AtMarket', 'MarketRange']:
            msg = "order_type must be 'AtMarket' or 'MarketRange'."
            raise ValueError(msg)

        if time_in_force not in ['IOC', 'GTC', 'FOK', 'DAY']:
            msg = "time_in_force must be in 'IOC', 'GTC', 'FOK', 'DAY'."
            raise ValueError(msg)

        params = {
                  'account_id': account_id,
                  'forSymbol': 'true',
                  'symbol': symbol,
                  'order_type': order_type,
                  'time_in_force': time_in_force
                 }

        self.__handle_request__(method='trading/close_all_for_symbol',
                                       params=params, protocol='post')

    def close_all(self, order_type='AtMarket', time_in_force='GTC',
                  account_id=None):
        """ Close all positions.

        Arguments:

        account_id: string,
            the order's account id.

        order_type: string (default: 'AtMarket'),
            the type of order execution, one of 'AtMarket' or 'MarketRange'.

        time_in_force: string (default: 'GTC'),
            the time in force of the order execution, must be one of
            'IOC', 'GTC', 'FOK' or 'DAY'.

        account_id: integer (Default None),
            the order's account id. If not given, the default account is used.

        """

        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')
        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        if order_type not in ['AtMarket', 'MarketRange']:
            msg = "order_type must be 'AtMarket' or 'MarketRange'."
            raise ValueError(msg)

        if time_in_force not in ['IOC', 'GTC', 'FOK', 'DAY']:
            msg = "time_in_force must be in 'IOC', 'GTC', 'FOK', 'DAY'."
            raise ValueError(msg)

        params = {
                  'account_id': account_id,
                  'forSymbol': 'false',
                  'symbol': '',
                  'order_type': order_type,
                  'time_in_force': time_in_force
                 }

        self.__handle_request__(method='trading/close_all_for_symbol',
                                       params=params, protocol='post')

    def open_trade(self, symbol, is_buy,
                   amount, time_in_force, order_type, rate=0,
                   is_in_pips=True, limit=None, at_market=0, stop=None,
                   trailing_step=None, account_id=None):
        """ Opens a trade for a given instrument.

        Arguments:

        symbol: string,
            the symbol of the instrument to trade as given by
            get_instruments().

        is_buy: boolean,
            True if the trade is a buy, False else.

        amount: integer,
            the trades amount in lots.

        order_type: string,
            the order type, must be 'AtMarket' or 'MarketRange'.

        time_in_force: string,
            the time in force of the order execution, must be one of
            'IOC', 'GTC', 'FOK' or 'DAY'.

        rate: float (default 0),
            the trades rate.

        is_in_pips: boolean (default True),
            whether the trades stop/limit rates are in pips.

        limit: float (default 0),
            the trades limit rate.

        at_market: float (default 0),
            the markets range.

        stop: float or None (default None),
            the trades stop rate.

        trailing_step: int or None (default None),
            the trailing step for the stop rate.

        account_id: integer (Default None),
            the trade's account id. If not given, the default account is used.

        """

        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')
        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        try:
            amount = int(amount)
        except:
            raise TypeError('amount must be an integer.')

        try:
            rate = float(rate)
        except:
            raise TypeError('rate must be a number.')

        if limit is not None:
            try:
                limit = float(limit)
            except:
                raise TypeError('limit must be a number.')

        try:
            at_market = float(at_market)
        except:
            raise TypeError('at_market must be a number.')

        if order_type not in ['AtMarket', 'MarketRange']:
            msg = "order_type must be 'AtMarket' or 'MarketRange'."
            raise ValueError(msg)

        if time_in_force not in ['IOC', 'GTC', 'FOK', 'DAY']:
            msg = "time_in_force must be in 'IOC', 'GTC', 'FOK', 'DAY'."
            raise ValueError(msg)

        if is_in_pips is True:
            is_in_pips = 'true'
        elif is_in_pips is False:
            is_in_pips = 'false'
        else:
            raise ValueError('is_in_pips must be True or False.')

        if is_buy is True:
            is_buy = 'true'
        elif is_buy is False:
            is_buy = 'false'
        else:
            raise ValueError('is_buy must be True or False.')

        if stop is not None:
            try:
                stop = float(stop)
            except:
                raise TypeError('stop must be a number.')

        if trailing_step is not None:
            try:
                trailing_step = int(trailing_step)      # DH change from float to int
            except:
                raise ValueError('trailing step must be a number.')

        params = {
                  'account_id': account_id,
                  'symbol': symbol,
                  'is_buy': is_buy,
                  'rate': rate,
                  'amount': amount,
                  'at_market': at_market,
                  'order_type': order_type,
                  'time_in_force': time_in_force,
                  'limit': limit,
                  'is_in_pips': is_in_pips
                 }

        if limit is not None:
            params['limit'] = limit
        if stop is not None:
            params['stop'] = stop
        if trailing_step is not None:
            params['trailing_step'] = trailing_step

        data = self.__handle_request__(method='trading/open_trade',
                                       params=params, protocol='post')
        if 'data' in data and 'orderId' in data['data']:
            order_id = int(data['data']['orderId'])
            # return data
        else:
            self.logger.warn('Missing orderId in servers answer.')
            return 0

        count = 0
        order = None
        while count < 10:
            try:
                order = self.get_order(order_id)
                break
            except:
                time.sleep(1)
                count += 1
                # order = self.get_order(order_id)
        if order is None:
            self.logger.warn('Can not find Order object, returning None.')
        return order

    def change_trade_stop_limit(self, trade_id, is_stop, rate, is_in_pips=True,
                                trailing_step=0):
        """ Change an trade's stop or limit rate.

        Arguments:

        trade_id: integer,
            the id of the trade to change.

        is_stop: boolean,
            defines whether the trade's limit (False) or the stop rate (True)
            is to be changed.

        rate: float,
            the new stop or limit rate.

        is_in_pips: boolean (Default True),
            whether the trade's stop/limit rates are in pips.

        trailing_step: int (Default 0),
            the trailing step for the stop rate.
        """

        try:
            trade_id = int(trade_id)
        except:
            raise TypeError('trade_id must be an integer.')

        if is_stop is True:
            is_stop = 'true'
        elif is_stop is False:
            is_stop = 'false'
        else:
            raise ValueError('is_stop must be a boolean.')

        try:
            rate = float(rate)
        except:
            raise TypeError('rate must be a number.')

        if is_in_pips is True:
            is_in_pips = 'true'
        elif is_in_pips is False:
            is_in_pips = 'false'
        else:
            raise ValueError('is_in_pips must be a boolean.')

        try:
            trailing_step = int(trailing_step)
        except:
            raise TypeError('trailing_step must be a number.')

        params = {
                  'trade_id': trade_id,
                  'is_in_pips': is_in_pips,
                  'is_stop': is_stop,
                  'rate': rate,
                  'trailing_step': trailing_step,
                 }

        meth = 'trading/change_trade_stop_limit'
        self.__handle_request__(method=meth, params=params,
                                protocol='post')

    def close_trade(self, trade_id, amount, order_type='AtMarket',
                    time_in_force='IOC', rate=None, at_market=None):
        """ Close a given trade.

        Arguments:

        trade_id: integer,
            the id of the trade.

        amount: integer (default 0),
            the trades amount in lots.

        order_type: string (default 'AtMarket'),
            the order type, must be 'AtMarket' or 'MarketRange'.

        time_in_force: string (default 'IOC'),
            the time in force of the order execution, must be one of
            'IOC', 'GTC', 'FOK' or 'DAY''.

        rate: float (default 0),
            the trades rate.

        at_market: float (default 0),
            the markets range.
        """
      
        try:
            trade_id = int(trade_id)
        except:
            raise TypeError('trade_id must be an integer.')

        try:
            amount = float(amount)
        except:
            raise TypeError('amount must be a number.')

        if order_type == 'MarketRange' and rate is not None:
            self.logger.warn("rate is ignored for order_type='MarketRange'")

        if rate is not None:
            try:
                rate = float(rate)
            except:
                raise TypeError('rate must be a number.')

        if order_type == 'MarketRange' and at_market is None:
            raise ValueError("at_market is required for order_type='MarketRange'")

        if at_market is not None:
            try:
                at_market = float(at_market)
            except:
                raise TypeError('at_market must be a number.')
            if at_market < 0:
                raise ValueError('at_market must bo greater or equal to zero')

        if order_type not in ['AtMarket', 'MarketRange']:
            msg = "order_type must be 'AtMarket' or 'MarketRange'."
            raise ValueError(msg)

        if time_in_force not in ['IOC', 'GTC', 'FOK', 'DAY']:
            msg = "time_in_force must be in 'IOC', 'GTC', 'FOK' or 'DAY'."
            raise ValueError(msg)

        params = {
                  'trade_id': trade_id,
                  'amount': amount,
                  'order_type': order_type,
                  'time_in_force': time_in_force
                 }
        if rate is not None and order_type != 'MarketRange':
            params['rate'] = rate

        if at_market is not None:
            params['at_market'] = at_market

        self.__handle_request__(method='trading/close_trade',
                                       params=params, protocol='post')

    def change_order(self, order_id, amount, rate, order_range=0,
                     trailing_step=None):
        """ Change amount, rate, order_range and / or trailling_step of an
        order.

        Arguments:

        order_id: int,
            the id of the order to change.

        amount: int,
            the new amount of the order.

        rate: float,
            the new rate of the order.

        order_range: float,
            the new range of the order. Only used for 'RangeEntry' orders,
            for other orders, it is 0 (default).

        trailing_step: int,
            the new trailing step for the order. Defaults to None.

        """

        try:
            order_id = int(order_id)
        except:
            raise TypeError('order_id must be an integer.')

        try:
            amount = float(amount)
        except:
            raise TypeError('amount must be a number.')

        try:
            rate = float(rate)
        except:
            raise TypeError('rate must be a number.')

        try:
            order_range = float(order_range)
        except:
            raise TypeError('order_range must be a number.')

        if trailing_step is not None:
            try:
                trailing_step = int(trailing_step)
            except:
                raise ValueError('trailing step must be a number.')

        params = {
                  'order_id': order_id,
                  'rate': rate,
                  'range': order_range,
                  'amount': amount
                 }
        if trailing_step is not None:
            params['trailing_step'] = trailing_step

        self.__handle_request__(method='trading/change_order',
                                       params=params, protocol='post')

    def delete_order(self, order_id):
        """ Delete an order.

        Arguments:

        order_id: integer,
            the id of the order to delete.

        """

        try:
            order_id = int(order_id)
        except:
            raise TypeError('order_id must be an integer.')

        if order_id in self.old_orders:
            self.logger.warn('Order is allready deleted.')
            return

        if order_id not in self.orders:
            raise ValueError('No order with order id %s' % order_id)

        params = {
                  'order_id': order_id
                 }

        self.__handle_request__(method='trading/delete_order',
                                       params=params, protocol='post')

    def create_market_buy_order(self, symbol, amount, account_id=None):
        """ Create an order to buy at market price.

        Arguments:

        symbol: string,
            the symbol of the instrument to trade as given by
            get_instruments().

        amount: integer,
            the trades amount in lots.

        account_id: integer (Default None),
            the trade's account id. If not given, the default account is used.

        """

        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')
        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        if symbol not in self.instruments:
            raise ValueError('Unknown symbol %s.' % symbol)

        try:
            amount = int(amount)
        except:
            raise TypeError('amount must be an integer.')

        order = self.open_trade(symbol, True, amount, 'FOK', 'AtMarket',
                                account_id)

        return order

    def create_market_sell_order(self, symbol, amount, account_id=None):
        """ Create an order to sell at market price.

        Arguments:

        symbol: string,
            the symbol of the instrument to trade as given by
            get_instruments().

        amount: integer,
            the trades amount in lots.

        account_id: integer (Default None),
            the trade's account id. If not given, the default account is used.

        """

        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')
        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        if symbol not in self.instruments:
            raise ValueError('Unknown symbol %s.' % symbol)

        try:
            amount = int(amount)
        except:
            raise TypeError('amount must be an integer.')

        order = self.open_trade(symbol, False, amount, 'FOK', 'AtMarket',
                                account_id)

        return order

    def create_entry_order(self, symbol, is_buy, amount, time_in_force,
                           order_type="Entry", limit=0, is_in_pips=True,
                           rate=0, stop=None, trailing_step=None, 
                           trailing_stop_step=None, order_range=None, 
                           expiration=None,
                           account_id=None):
        """ Creates an entry order for a given instrument.

        Arguments:

        account_id: integer (Default None),
            the trading account's id. If None, the default account is used.

        symbol: string,
            the symbol of the instrument to trade as given by
            get_instruments().

        is_buy: boolean,
            True if the trade is a buy, False else.

        amount: integer,
            the trades amount in lots.

        order_type: string,
            the order type, must be 'Entry' (default) or 'RangeEntry'.

        time_in_force: string,
            the time in force of the order execution, must be one of
            'GTC', 'DAY', 'IOC', 'FOK' or 'GTD'.

        rate: float (default 0),
            the trades rate.

        is_in_pips: boolean (default True),
            whether the trade's stop/limit rates are in pips.

        limit: float (default 0),
            the trades limit rate.

        stop: float or None (default None),
            the trades stop rate.

        trailing_step: int or None (default None),
            the trailing step for the stop rate.

        trailing_stop_step: float or None (default None),
            the trailing step for the order stop rate.

        order_range: float or None (default),
            the order's range if order type is 'RangeEntry'.

        expiration: datetime.datetime, datetime.date or string (defaut None),
            order's expiration date for 'GTD'. 

        Returns:

        The id of the new order.
        """
        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')
        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        try:
            amount = int(amount)
        except:
            raise TypeError('amount must be an integer.')

        if symbol not in self.instruments:
            raise ValueError('Unknown symbol %s.' % symbol)

        try:
            rate = float(rate)
        except:
            raise TypeError('rate must be a number.')

        try:
            limit = float(limit)
        except:
            raise TypeError('limit must be a number.')

        if order_type not in ['Entry', 'RangeEntry']:
            msg = "order_type must be 'Entry' or 'RangeEntry'."
            raise ValueError(msg)

        if time_in_force not in ['GTC', 'DAY', 'GTD', 'IOC', 'FOK'] :
            msg = "time_in_force must be 'GTC', 'DAY', 'IOC', 'FOK', or 'GTD'."
            raise ValueError(msg)

        if is_in_pips is True:
            is_in_pips = 'true'
        elif is_in_pips is False:
            is_in_pips = 'false'
        else:
            raise ValueError('is_in_pips must be True or False.')

        if is_buy is True:
            is_buy = 'true'
        elif is_buy is False:
            is_buy = 'false'
        else:
            raise ValueError('is_buy must be True or False.')

        if stop is not None:
            try:
                stop = float(stop)
            except:
                raise TypeError('stop must be a number.')

        if trailing_step is not None:
            try:
                trailing_step = int(trailing_step)
            except:
                raise ValueError('trailing_step must be a number.')

        if trailing_stop_step is not None:
            try:
                trailing_stop_step = int(trailing_stop_step) 
            except:
                raise ValueError('trailing_stop_step must be a number.')

        if order_range is not None:
            try:
                order_range = float(order_range)
            except:
                raise ValueError('order_range must be a number.')
        elif order_type == 'RangeEntry':
            msg = "If order type is 'RangeEntry', order_range must be given."
            raise ValueError(msg)

        if expiration:
            if isinstance(expiration, str):
                try:
                    expiration = pd.Timestamp(expiration).to_pydatetime()
                except:
                    msg = "Can not convert parameter expiration to datetime." 
                    raise ValueError(msg)

            elif (isinstance(expiration, dt.datetime) or 
                  isinstance(expiration, dt.date)):
                pass
            else:
                msg = "expiration must either be a datetime object or a string"
                raise ValueError(msg)

            expi = expiration.strftime('%Y-%m-%d %H:%M')
        elif time_in_force == 'GTD':
            msg = "If time_in_force is 'GTD', expiration must be given."
            raise ValueError(msg)


        params = {
                  'account_id': account_id,
                  'symbol': symbol,
                  'is_buy': is_buy,
                  'rate': rate,
                  'amount': amount,
                  'limit': limit,
                  'order_type': order_type,
                  'is_in_pips': is_in_pips,
                  'time_in_force': time_in_force
                 }

        if stop is not None:
            params['stop'] = stop
        if trailing_step is not None:
            params['trailing_step'] = trailing_step
        if trailing_stop_step is not None:
            params['trailing_stop_step'] = trailing_stop_step
        if order_range is not None:
            params['range'] = order_range
        if expiration is not None:
            params['expiration'] = expi

        data = self.__handle_request__(method='trading/create_entry_order',
                                       params=params, protocol='post')

        if 'data' in data and 'orderId' in data['data']:
            order_id = int(data['data']['orderId'])

        else:
            self.logger.warn('Missing orderId in servers answer.')
            return 0

        try:
            order = self.get_order(order_id)
        except:
            time.sleep(1)
            order = self.get_order(order_id)

        return order

    def change_order_stop_limit(self, order_id, stop=None, limit=None,
                                is_stop_in_pips=True, is_limit_in_pips=True):
        """ Change an order's stop and / or limit rate. To let an attribute
        unchanged set the values parameter to None.

        Arguments:

        order_id: integer,
            the id of the order to change.

        stop: float or None (Default),
            the new stop rate.

        limit: float or None (Default),
            the new limit rate.

        is_stop_in_pips: boolean (Default True),
            whether the order's stop rate is in pips.

        is_limit_in_pips: boolean (Default True),
            whether the order's limit rate is in pips.
        """

        try:
            order_id = int(order_id)
        except:
            raise TypeError('order_id must be an integer.')

        params = {
                  'order_id': order_id
                 }

        if stop is not None:
            if is_stop_in_pips is True:
                is_stop_in_pips = 'true'
            elif is_stop_in_pips is False:
                is_stop_in_pips = 'false'
            else:
                raise ValueError('is_stop_in_pips must be a boolean.')

            try:
                stop = float(stop)
            except:
                raise TypeError('stop must be a number.')

            params['is_stop_in_pips'] = is_stop_in_pips
            params['stop'] = stop

        if limit is not None:
            if is_limit_in_pips is True:
                is_limit_in_pips = 'true'
            elif is_limit_in_pips is False:
                is_limit_in_pips = 'false'
            else:
                raise ValueError('is_limit_in_pips must be a boolean.')

            try:
                limit = float(limit)
            except:
                raise TypeError('limit')

            params['is_limit_in_pips'] = is_limit_in_pips
            params['limit'] = limit

        meth = 'trading/change_order_stop_limit'
        self.__handle_request__(method=meth, params=params,
                                protocol='post')

    def create_oco_order(self, symbol, is_buy, is_buy2, amount, is_in_pips,
                         time_in_force, at_market, order_type,
                         limit=0, limit2=0, rate=0, rate2=0, stop=0, stop2=0,
                         trailing_step=0, trailing_step2=0,
                         trailing_stop_step=0, trailing_stop_step2=0,
                         account_id=None):

        """ Creates an entry order for a given instrument.

        Arguments:

        account_id: integer (Default None),
            the id of the trading account. If None, the default account is
            used.

        symbol: string,
            the symbol of the instrument to trade as given by
            get_instruments().

        is_buy: boolean,
            True if the first order is a buy, False else.

        is_buy2: boolean,
            True if the second order is a buy, False else.

        amount: integer,
            the trades amount in lots.

        is_in_pips: boolean (default True),
            whether the order's stop/limit rates are in pips.

        time_in_force: string,
            the time in force of the order execution, must be one of
            'GTC', 'DAY' or 'GTD'.

        at_market: float (default 0),
            the order's markets range.

        order_type: string,
            the order type, must be 'Entry'.

        limit: float (default 0),
            the first order's limit rate.

        limit2: float (default 0),
            the second order's limit rate.

        rate: float (default 0),
            the first order's rate.

        rate:2 float (default 0),
            the second order's rate.

        stop: float (default 0),
            the first order's stop rate.

        stop2: float (default 0),
            the second order's stop rate.

        trailing_step: int (default 0),
            the trailing step for the first order.

        trailing_step2: int (default 0),
            the trailing step for the second order.

        trailing_stop_step: float (default 0),
            the trailing step for the first order's stop rate.

        trailing_stop_step: float (default 0),
            the trailing step for the second order's stop rate.

        Returns:

        The id of the new order.
        """
        if account_id is None:
            account_id = self.default_account
        else:
            try:
                account_id = int(account_id)
            except:
                raise TypeError('account_id must be an integer.')

        if account_id not in self.account_ids:
            raise ValueError('Unknown account id %s.' % account_id)

        if is_buy is True:
            is_buy = 'true'
        elif is_buy is False:
            is_buy = 'false'
        else:
            raise ValueError('is_buy must be a boolean.')

        if is_buy2 is True:
            is_buy2 = 'true'
        elif is_buy2 is False:
            is_buy2 = 'false'
        else:
            raise ValueError('is_buy2 must be a boolean.')

        try:
            amount = int(amount)
        except:
            raise TypeError('amount must be an integer.')

        if is_in_pips is True:
            is_in_pips = 'true'
        elif is_in_pips is False:
            is_in_pips = 'false'
        else:
            raise ValueError('is_in_pips must be a boolean.')

        if time_in_force not in ['IOC', 'GTC', 'FOK', 'DAY']:
            msg = "time_in_force must be 'IOC', 'GTC', 'FOK' or 'DAY'."
            raise ValueError(msg)

        try:
            at_market = float(at_market)
        except:
            raise TypeError('at_market must be a number.')

        if order_type not in ['AtMarket', 'MarketRange']:
            msg = "order_type must one of 'AtMarket' or 'MarketRange'."
            raise ValueError(msg)

        try:
            limit = float(limit)
        except:
            raise TypeError('limit must be a number.')

        try:
            limit2 = float(limit2)
        except:
            raise TypeError('limit2 must be a number.')

        try:
            rate = float(rate)
        except:
            raise TypeError('rate must be a number.')

        try:
            rate2 = float(rate2)
        except:
            raise TypeError('rate2 must be a number.')

        try:
            stop = float(stop)
        except:
            raise TypeError('stop must be a number.')

        try:
            stop2 = float(stop2)
        except:
            raise TypeError('stop2 must be a number.')

        try:
            trailing_step = int(trailing_step)
        except:
            raise ValueError('trailing step must be a number.')

        try:
            trailing_step2 = int(trailing_step2)
        except:
            raise ValueError('trailing step must be a number.')

        try:
            trailing_stop_step = int(trailing_stop_step)        # DH replace float to int
        except:
            raise ValueError('trailing_stop_step must be a number.')

        try:
            trailing_stop_step2 = int(trailing_stop_step2)      # DH replace float to int
        except:
            raise ValueError('trailing_stop_step2 must be a number.')

        params = {
                  'account_id': account_id,
                  'symbol': symbol,
                  'amount': amount,
                  'at_market': at_market,
                  'order_type': order_type,
                  'is_in_pips': is_in_pips,
                  'time_in_force': time_in_force,
                  'is_buy': is_buy,
                  'is_buy2': is_buy2,
                  'rate': rate,
                  'rate2': rate2,
                  'stop': stop,
                  'stop2': stop2,
                  'limit': limit,
                  'limit2': limit2,
                  'trailing_step': trailing_step,
                  'trailing_step2': trailing_step2,
                  'trailing_stop_step': trailing_stop_step,
                  'trailing_stop_step2': trailing_stop_step2,
                 }

        data = self.__handle_request__(method='trading/simple_oco',
                                       params=params, protocol='post')

        if 'data' not in data:
            self.logger.error('Missing data in server response: %s.' % data)
            raise ServerError('Missing data in server response.')

        orders = list()
        for data_set in data['data']:
            count = 0
            while count < 100:
                if int(data_set['orderId']) not in self.orders:
                    time.sleep(1)
                    count += 1
                else:
                    orders.append(self.get_order(int(data_set['orderId'])))
                    break
            else:
                raise ValueError('No order with id %s' % data_set['orderId'])

        bulk_id = orders[0].__ocoBulkId__
        oco_order = fxcmpy_oco_order(bulk_id, orders, self,  self.logger)
        self.oco_orders[bulk_id] = oco_order
        return oco_order

    def add_to_oco(self, order_ids, oco_bulk_id=0):
        """ Add orders to OCO Orders.

        Arguments:

        order_ids: list of order_ids,
            the ids of the orders to add to the OCO Order.

        co_bulk_id: integer, default = 0,
            the id of the OCO Order, if 0 a new OCO Order will be created.

        """

        try:
            _ = (int(i) for i in order_ids)
        except:
            raise TypeError('order_ids must be a list of integers.')

        try:
            oco_bulk_id = int(oco_bulk_id)
        except:
            raise TypeError('oco_bulk_id must be an integer.')

        params = {
                  'orderIds': order_ids,
                  'ocoBulkId': oco_bulk_id
                 }
        self.__handle_request__(method='trading/add_to_oco',
                                       params=params, protocol='post')

    def remove_from_oco(self, order_ids):
        """ Remove orders from OCO Orders.

        Arguments:

        order_ids: list of order_ids,
            the ids of the orders to remove from OCO Orders.

        """
        try:
            _ = (int(i) for i in order_ids)
        except:
            raise TypeError('order_ids must be a list of integers.')

        params = {
                  'orderIds': order_ids
                 }
        self.__handle_request__(method='trading/remove_from_oco',
                                       params=params, protocol='post')

    def edit_oco(self, oco_bulk_id, add_order_ids=None,
                 remove_order_ids=None):
        """Add or remove orders to or from OCO Orders.

        Arguments:

        oco_bulk_id: integer,
            the id of the OCO Order.

        add_order_ids: list of order_ids,
            the id's of the orders to add to OCO Orders.

        remove_order_ids: list of order_ids,
            the id's of the orders to remove from OCO Orders.

        """
        if add_order_ids is None:
            add_order_ids = list()

        if remove_order_ids is None:
            remove_order_ids = list()

        try:
            _ = (int(i) for i in add_order_ids)
        except:
            raise TypeError('add_order_ids must be a list of integers.')

        try:
            _ = (int(i) for i in remove_order_ids)
        except:
            raise TypeError('remove_order_ids must be a list of integers.')

        params = {
                  'ocoBulkId': oco_bulk_id,
                  'addOrderIds': add_order_ids,
                  'removeOrderIds': remove_order_ids
                 }
        self.__handle_request__(method='trading/edit_oco',
                                       params=params, protocol='post')

    def get_instruments_for_candles(self):
        """ Return a list of all available instruments to receive historical
        data for."""

        return list(self.offers.keys())

    def get_candles(self, instrument='', offer_id=None, period='H1', number=10,
                    start=None, end=None, with_index=True, columns=[], 
                    stop=None):
        """Return historical data from the fxcm database as pandas.DataFrame.

        Arguments:

        instrument: string (default ''):
            the instrument for which data is requested. For a list of all
            available instruments for historical data, use
            get_instruments_for_candles().
            If the value is equal to '' (default), offer_id must have a value. 
            If both, instrument and offer_id are given, the value of instrument 
            is used.

        offer_id: integer (default None): 
            the id of the instrument for which data is requested as given in the
            offer trading table as given by get_offers(). If offer_id is equal 
            to None (default), the parameter instrument must have a value. 
            If both, instrument and offer_id are given, the value of instrument 
            is used.

        period: string,
            the granularity of the data. Must be one of
            'm1', 'm5', 'm15', 'm30', 'H1', 'H2', 'H3', 'H4', 'H6', 'H8',
            'D1', 'W1', or 'M1'.

        number: integer (default 10),
            the number of candles to receive.

        start: datetime.datetime, datetime.date or string (defaut None),
            the first date to receive data for. 

        end: datetime.datetime, datetime.date or string (default None),
            the last date to receive data for.

        with_index: boolean (default True),
            whether the column 'date' should server as index in the resulting
            pandas.DataFrame.

        columns: list (default list()),
            a list of column labels the result should include. If empty, all
            columns are returned.

            Available column labels are

            'date', 'bidopen', 'bidclose', 'bidhigh', 'bidlow',
            'askopen', 'askclose', 'askhigh', 'asklow', 'tickqty'.

            Also available is 'asks' as shortcut for all ask related columns
            and 'bids' for all bid related columns, respectively.

            The column 'date' is always included.

        Returns:

        A pandas DataFrame containing the requested data.

        """

        if instrument == '' and offer_id is None:
            self.logger.error('Error in get_candles: No instrument given!.')
            msg = 'Please provide either an instrument or an offer_id'
            raise ValueError(msg)
        elif instrument != '':
            if offer_id is not None:
                msg = "Both, instrument and offer_id are given, "
                msg += "taking the value of instrument." 
                self.logger.warn(msg)
            if instrument in self.offers:
                offer_id = self.offers[instrument]
            else:
                self.logger.error('Unknown instrument: %s' % instrument)
                raise ValueError('Instrument must be one of %s.'
                                 % str(tuple(self.offers.keys())))
        else:
            if offer_id not in self.offers.values():
                self.logger.error('Unknown offer_id: %s' % offer_id)
                raise ValueError('Unknown offer_id: %s' % offer_id)

        if period not in self.PERIODS:
            self.logger.error('Error in get_candles: Illegal period: %s.'
                              % period)
            raise ValueError('period must be one of %s.' % self.PERIODS)
        if type(number) != int or number < 1 or number > 10000:
            self.logger.error('Error in get_candles: Illegal param. number: %s'
                              % number)
            raise ValueError('number must be a integer betwenn 0 and 10000.')

        params = {
                  'num': number,
                 }

        if start:
            if isinstance(start, str):
                try:
                    start = pd.Timestamp(start).to_pydatetime()
                except:
                    msg = "Can not convert parameter start to datetime."
                    raise ValueError(msg)

            elif isinstance(start, dt.datetime) or isinstance(start, dt.date):
                pass
            else:
                msg = "start must either be a datetime object or a string"
                raise ValueError(msg)

            start = ((start - dt.datetime(1970, 1, 1)) / 
                     dt.timedelta(seconds=1))
            try:
                start = int(start)
            except:
                self.logger.error('Error in get_candles:')
                self.logger.error('Illegal value for start: %s.' % start)
                raise ValueError('start must be a datetime object.')
            params['from'] = max(start, 1)

        if end == None and stop is not None:
            end = stop

        if end:
            if isinstance(end, str):
                try:
                    end = pd.Timestamp(end).to_pydatetime()
                except:
                    msg = "Can not convert parameter end to datetime."
                    raise ValueError(msg)

            elif isinstance(end, dt.datetime) or isinstance(end, dt.date):
                pass
            else:
                msg = "end must either be a datetime object or a string"
                raise ValueError(msg)

            end = ((end - dt.datetime(1970, 1, 1)) / dt.timedelta(seconds=1))
            try:
                end = int(end)
            except:
                self.logger.error('Error in get_candles:')
                self.logger.error('Illegal value for end: %s.' % stop)
                raise ValueError('end must be a datetime object.')
            params['to'] = max(end, 1)

        data = self.__handle_request__(method='candles/%s/%s'
                                       % (offer_id, period), params=params)

        if len(columns) == 0:
            to_add = self.CANDLES_COLUMNS
        else:
            to_add = ['date', ]
        for field in columns:
            if field == 'asks':
                for ask_field in self.CANDLES_COLUMNS_ASK:
                    if ask_field not in to_add:
                        to_add.append(ask_field)
            elif field == 'bids':
                for bid_field in self.CANDLES_COLUMNS_BID:
                    if bid_field not in to_add:
                        to_add.append(bid_field)
            elif field in self.CANDLES_COLUMNS:
                if field not in to_add:
                    to_add.append(field)
            else:
                msg = "Unknown field '%s', please use one or more of \
'%s', 'asks', 'bids'."
                raise ValueError(msg % (field,
                                        "','".join(self.CANDLES_COLUMNS)))

        if 'candles' in data:
            while None in data['candles']:
                data['candles'].remove(None)
            ret = pd.DataFrame(data['candles'], columns=self.CANDLES_COLUMNS)
            ret['date'] = pd.to_datetime(ret['date'], unit='s')
        else:
            ret = pd.DataFrame(columns=self.CANDLES_COLUMNS)

        ret = ret[to_add]

        if with_index:
            ret.set_index('date', inplace=True)
        return ret

    def __collect_account_ids__(self):
        """ Collects account ids and stores them in self.account_ids."""

        self.account_ids = set()
        data = self.get_accounts('list')
        for acc in data:
            if 'accountId' in acc and acc['accountId'] != '':
                self.account_ids.add(int(acc['accountId']))
        self.account_ids = list(self.account_ids)

    def __collect_orders__(self):
        """ Collects available orders and stores them in self.orders."""

        data = self.get_orders('list')
        for order in data:
            if 'orderId' in order and order['orderId'] != '':
                self.orders[int(order['orderId'])] = fxcmpy_order(self, order)
        self.orders_set = True

    def __collect_oco_orders__(self):
        """ Collect available oco orders and stores them in self.oco_orders."""

        for order in self.orders.values():
            if order.__ocoBulkId__ != 0:
                if order.__ocoBulkId__ in self.oco_orders:
                    self.oco_orders[order.__ocoBulkId__].__add__(order)
                else:
                    oco = fxcmpy_oco_order(order.__ocoBulkId__, [order, ], self,
                                         self.logger)
                    self.oco_orders[order.__ocoBulkId__] = oco
        self.oco_orders_set = True

    def __get_instruments_table__(self):
        """ Return the instruments table of FXCM."""

        self.logger.debug('Fetching instruments table.')

        try:
            data = self.__handle_request__(method='trading/get_instruments')
        except:
            self.logger.warning('Can not fetch instruments table from server.')
            data = list()
        return data

    def __collect_offers__(self):
        """ Collect available offers and stores them in self.offers, a dict
        with key symbol and value offer_id."""
        self.offers = fxcmpy_instruments.inst
        data = self.__get_instruments_table__()

        to_add = list()
        to_unsubscribe = list()
        if 'instrument' in data['data']:
            instruments = data['data']['instrument']
            for ins in instruments:
                if ins['symbol'] not in self.offers:
                    to_add.append(ins['symbol'])
                    if ins['visible'] is False:
                        to_unsubscribe.append(ins['symbol'])
                        self.subscribe_instrument(ins['symbol'])

        offers = self.get_offers('list')
        for offer in offers:
            if 'currency' in offer and 'offerId' in offer:
                if offer['currency'] in to_add:
                    self.offers[offer['currency']] = int(offer['offerId'])
                if offer['currency'] in to_unsubscribe:
                    self.unsubscribe_instrument(offer['currency'])
        self.offers_set = True

    def __collect_positions__(self):
        data = self.get_open_positions('list')
        for pos in data:
            if 'tradeId' in pos and pos['tradeId'] != '':
                self.open_pos[int(pos['tradeId'])] = fxcmpy_open_position(self,
                                                                          pos)
        data = self.get_closed_positions('list')
        for po in data:
            if 'tradeId' in po and po['tradeId'] != '':
                self.closed_pos[int(po['tradeId'])] = fxcmpy_closed_position(self,
                                                                             po)
        self.positions_set = True

    def __update__instrument_subscription__(self, symbol, visible):
        """ Update the subscription of an instrument to the offers table.

        Arguments:

        symbol, string:
            the symbol of the instrument to activate.
        visible, bool: 
            flag whether to subscribe or unsubscribe the instrument.

        Returns:
            True by success and False else.
        """

        if visible:
            visible = 'true'
        else:
            visible = 'false'

        if self.number_update_requests > 48:
            msg = 'Max. number of update request reached, renewing connection.'

            self.logger.warning(msg)
            if self.is_connected():
                self.socket.disconnect()
                time.sleep(1)

            self.number_update_requests = 0
        else:
            self.number_update_requests  += 1

        try:
            self.__handle_request__(method='trading/update_subscriptions',
                                    params={'symbol':symbol, 'visible':visible},
                                    protocol='post')
        except:
            self.logger.warning('Can not unsubscribe instrument %s' % symbol)
            return False
        return True

    def __connect__(self):
        try:
            self.logger.debug('Access token: %s.' % self.access_token)
            self.socket = SocketIO(self.trading_url+':443', self.port,
                                   params={'access_token': self.access_token,
                                           'agent': 'pythonquants'},
                                   wait_for_connection=False, 
                                   proxies = self.proxies)
            self.logger.info('Socket established: %s.' % self.socket)
            # self.socket_id = self.socket._engineIO_session.id
            # self.logger.warn('Got socket session id: %s.' % self.socket_id)
            
        except ConnectionError as inst:
            self.connection_status = 'aborted'
            self.logger.error('Socket returns an error: %s.'
                              % inst.args[0])
        except:
            self.connection_status = 'aborted'
            self.logger.error('Socket returns unknown error.')
        else:
            self.__disconnected__ = False
            self.socket.on('connect',self.__on_connect__)
            self.socket.on('disconnect',self.__on_disconnect__)
            self.socket.on('connect_error',self.__on_connection_error__)
            self.socket.on('error', self.__on_error__)
            self.socket.wait()

    def __reconnect__(self, count):
        self.logger.warning('Not connected, try to reconnect. (%s)' % count)
        try:
            self.socket_thread.join()
        except:
            self.logger.error('Failed to join task')
        self.socket = None
        self.request_header = None
        self.default_account = None
        self.instruments = None
        self.prices = dict()
        self.account_ids = set()
        self.orders = dict()
        self.old_orders = dict()
        self.offers = dict()
        self.open_pos = dict()
        self.closed_pos = dict()
        self.oco_orders = dict()
        # self.add_callbacks = dict()
        self.connection_status = 'unset'

        time.sleep(5)
        self.connect()
        time.sleep(5)
        self.subscribe_data_model('Order')
        self.subscribe_data_model('OpenPosition')
        self.subscribe_data_model('ClosedPosition')
        for symbol in self.prices:
            params = {'pairs': symbol}
            self.__handle_request__(method='subscribe', params=params,
                                    protocol='post')
            self.socket.on(symbol, self.__on_price_update__)

    def __handle_request__(self, method='', params=None, protocol='get'):
        """ Sends server requests. """

        if params is None:
            params = {}

        # print("params=", params)
        if method == '':
            self.logger.error('Error in __handle__requests__: No method given')
            raise ValueError('No method given.')
        if type(params) is not dict:
            self.logger.debug('Error in __handle__requests__:')
            self.logger.debug('params must be of type dict.')
            raise TypeError('params must be of type dict.')

        self.logger.info('In handle_request with method %s' % method)
        self.logger.info('Connection status: %s' % self.is_connected())
        self.logger.info('2. connection status: %s' % self.connection_status) 
        self.logger.info('Socket state: %s' % self.socket.connected)
        self.logger.info('Thread state: %s' % self.socket_thread.is_alive())
        self.logger.info('Thread name: %s' % self.socket_thread.name)
        self.logger.info('Socket id: %s' % self.socket._engineIO_session.id)

        if not self.is_connected():
            count = 1
            while not self.is_connected() and count < 11:
                self.__reconnect__(count)
                count += 1
                time.sleep(5)
        if not self.is_connected():
            self.logger.error('Connection aborted, failed to reconnect')
            raise IOError('Connection aborted, failed to reconnect')

        self.socket_id = self.socket._engineIO_session.id
        self.bearer_token = 'Bearer '+self.socket_id+self.access_token
        self.logger.info('Created bearer token: %s' % self.bearer_token) 
        self.request_headers = {
                                'User-Agent': 'request',
                                'Authorization': self.bearer_token,
                                'Accept': 'application/json',
                                'Content-Type':
                                'application/x-www-form-urlencoded'
                               }

        if method == 'trading/close_all_for_symbol':
            if ('forSymbol' in params and params['forSymbol'] == 'false'
                    and len(self.open_pos) == 0):
                self.logger.warning('No open positions to close')
                return False
            elif 'forSymbol' in params and params['forSymbol'] == 'true':
                count = 0
                for pos in self.open_pos.values():
                    if pos.__currency__ == params['symbol']:
                        count += 1
                if count == 0:
                    self.logger.warn('No open positions to close.')
                    return False

        self.logger.info('Sending request to %s/%s, parameter: %s.'
                         % (self.trading_url, method, params))

        if protocol == 'post':
            req = requests.post('%s:443/%s' % (self.trading_url, method),
                                headers=self.request_headers, data=params,
                                proxies=self.proxies)
            self.logger.info('Sending POST Request:')
            self.logger.info('URL: %s' % req.url)
            self.logger.info('Payload: %s' % req.request.body)
            self.logger.info('Headers: %s' % req.request.headers)
            self.logger.info('Params: %s' % params)
            self.logger.info('Proxies: %s' % self.proxies)

        else:
            req = requests.get('%s:443/%s' % (self.trading_url, method),
                               headers=self.request_headers, params=params,
                               proxies=self.proxies)
            self.logger.info('Sending GET Request:')
            self.logger.info('URL: %s' % req.url)
            self.logger.info('Headers: %s' % req.request.headers)
            self.logger.info('Params: %s' % params)
            self.logger.info('Proxies: %s' % self.proxies)

        if req.status_code != 200:
            self.logger.error('FXCM reject req %s with status %s and msg %s.'
                              % (method, req.status_code, req.text))

            raise ServerError('Request returns status code %s and message "%s"'
                              % (req.status_code,
                                 unquote(req.text)))

        data = None
        try:
            data = req.json()
        except:
            self.logger.error('Can not parse server answer to json object: %s.'
                              % req.text)

        if 'response' not in data or 'executed' not in data['response']:
            self.logger.error('Malformed response %s' % data)
            raise ServerError('Malformed response')

        if not data['response']['executed']:
            if 'error' in data['response'] and data['response']['error'] != '':
                self.logger.error('Server reports an error: %s.'
                                    % data['response'])
                self.logger.error('URL: %s' % req.url)
                self.logger.error('Headers: %s' % req.request.headers)
                self.logger.error('Params: %s' % params)
                self.logger.error('Bearer token: %s' % self.bearer_token)
                self.logger.error('Connection status: %s'
                                    % self.connection_status)
                self.logger.error('Socket session id: %s'
                                    % self.socket._engineIO_session.id)

                raise ServerError('FXCM Server reports an error: %s.'
                                    % data['response']['error'])
            else:
                self.logger.error('FXCM Server reports an unknown error: %s.'
                                    % data['response'])
                raise ServerError('FXCM Server returns an unknown error.')

        self.logger.debug('Server answer: %s.' % data)

        return data

    def __on_price_update__(self, msg):
        data = json.loads(msg)
        symbol = data['Symbol']
        date = pd.to_datetime(int(data['Updated']), unit='ms')
        temp_data = pd.DataFrame([data['Rates']],
                                 columns=['Bid', 'Ask', 'High', 'Low'],
                                 index=[date])
        if symbol not in self.prices:
            self.prices[symbol] = temp_data
        else:
            self.prices[symbol] = pd.concat([self.prices[symbol], temp_data])
            if self.max_prices is not None and (len(self.prices[symbol]) > 
                                                self.max_prices):
                msg = 'Max. length of prices exceeded (%s), dropping oldest.'
                self.logger.info(msg % self.max_prices)
                self.prices[symbol] = self.prices[symbol].iloc[-self.max_prices:]

        if symbol in self.add_callbacks:
            callbacks = self.add_callbacks[symbol]
            for func in callbacks:
                try:
                    # t = Thread(target=callbacks[func],
                    #           args=(data, self.prices[symbol]))
                    # t.start()
                    callbacks[func](data, self.prices[symbol])
                except:
                    self.logger.error('Call of %s raised an error:' % func)
                    self.logger.error(sys.exc_info()[0])
                    self.logger.error(sys.exc_info()[1])
                    raise

    def __on_model_update__(self, msg):
        # Answers not always json objects, so we have to log the raw answer
        # data = json.loads(msg)
        try:
            self.logger.debug(msg)
        except:
            pass

    def __on_message__(self, msg):
        # Answers not always json objects, so we have to log the raw answer
        try:
            data = json.loads(msg)
            self.logger.debug(data)
        except:
            pass

    def __on_order_update__(self, msg):
        """ Gets called when the order stream sends new data for the order
        table.

        Arguments:

        msg: string,
            a json like data object.
        """
    
        if not self.orders_set:
            return 0

        try:
            data = json.loads(msg)
        except:
            self.logger.warning('Got a non json answer in order stream, ignoring')
            self.logger.warning(msg)
            return -1
        if 'action' in data and data['action'] == 'I':
            self.logger.info('Got a insert event for orders: %s.' % data)
            order_id = int(data['orderId'])
            self.orders[order_id] = fxcmpy_order(self, data)

        elif 'action' in data and data['action'] == 'D':
            self.logger.warning('Got a delete event for orders: %s.' % data)
            order_id = int(data['orderId'])
            if order_id in self.orders:
                order = self.orders[order_id]
                if order.get_ocoBulkId() != 0:
                    try:
                        self.oco_orders[order.get_ocoBulkId()].__remove__(order)
                    except:
                        pass

                self.old_orders[order_id] = order
                del self.orders[order_id]

        elif ('action' in data and
              data['action'] != 'I' and data['action'] != 'D' and
              data['action'] != 'U'):
            msg = 'Found an unknown action in Order stream: %s.' % data
            self.logger.error(msg)
        else:
            self.logger.debug('Update data without action:')
            self.logger.debug(data)
            if 'orderId' in data:
                try:
                    order = self.orders[int(data['orderId'])]
                except:
                    msg = 'Got update for unknown order id: %s.' % data['orderId']
                    self.logger.warn(msg)
                    return 0
                for field in data:
                    if (field == 'ocoBulkId' and
                            order.get_ocoBulkId() != data['ocoBulkId']):
                        if data['ocoBulkId'] == 0:
                            bulkId = order.get_ocoBulkId()
                            self.oco_orders[bulkId].__remove__(order)
                        else:
                            if data['ocoBulkId'] not in self.oco_orders:
                                self.__collect_oco_orders__()
                            self.oco_orders[data['ocoBulkId']].__add__(order)

                        value = data['ocoBulkId']
                    else:
                        value = data[field]
                    order.__set_attribute__(field, value)

        if 'Order' in self.add_callbacks:
            callbacks = self.add_callbacks['Order']
            for func in callbacks:
                try:
                    callbacks[func](data)
                except:
                    self.logger.error('Call of %s raised an error:' % func)
                    self.logger.error(sys.exc_info()[0])
                    self.logger.error(sys.exc_info()[1])
                    self.logger.error(sys.exc_info()[2])

    def __on_open_pos_update__(self, msg):
        """ Gets called when the open_position stream sends new data.

        Arguments:

        msg: string,
            a json like data object.
        """
        if not self.positions_set: 
            return 0

        try:
            data = json.loads(msg)
        except:
            msg = 'Got non json answer in open pos stream, ignoring.'
            self.logger.warning(msg)
            self.logger.warning(msg)
            return -1

        if 'tradeId' in data and data['tradeId'] != '':
            trade_id = int(data['tradeId'])
            if 'action' in data and data['action'] == 'I':
                self.logger.warning('Got a insert event for open positions: %s.'
                                 % data)
                self.open_pos[trade_id] = fxcmpy_open_position(self, data)
            elif 'action' in data and data['action'] == 'D':
                self.logger.warning('Got a delete event for open posi: %s' % data)
                del self.open_pos[trade_id]

            elif ('action' in data and
                  data['action'] != 'I' and data['action'] != 'D' and
                  data['action'] != 'U'):
                msg = 'Found an unknown action in open pos stream: %s.' % data
                self.logger.error(msg)
            else:
                self.logger.debug('Update data without action:')
                self.logger.debug(data)
                pos = self.open_pos[trade_id]
                for field in data:
                    pos.__set_attribute__(field, data[field])

        if 'OpenPosition' in self.add_callbacks:
            callbacks = self.add_callbacks['OpenPosition']
            for func in callbacks:
                try:
                    callbacks[func](data)
                except:
                    self.logger.error('Call of %s raised an error:' % func)
                    self.logger.error(sys.exc_info()[0])
                    self.logger.error(sys.exc_info()[1])
                    self.logger.error(sys.exc_info()[2])

    def __on_closed_pos_update__(self, msg):
        """ Gets called when the closed_position stream sends new data.

        Arguments:

        msg: string,
            a json like data object.
        """
        if not self.positions_set:
            return 0

        try:
            data = json.loads(msg)
        except:
            msg = 'Got non json answer in close pos stream, ignoring.'
            self.logger.warning(msg)
            self.logger.warning(msg)
            return -1

        if 'tradeId' in data and data['tradeId'] != '':
            trade_id = int(data['tradeId'])
            if 'action' in data and data['action'] == 'I':
                self.logger.warning('Got a insert event for closed positions: %s.'
                                 % data)
                self.closed_pos[trade_id] = fxcmpy_closed_position(self, data)
            elif 'action' in data and data['action'] == 'D':
                self.logger.warning('Got delete event for closed pos: %s' % data)
                del self.closed_pos[trade_id]

            elif ('action' in data and
                  data['action'] != 'I' and data['action'] != 'D' and
                  data['action'] != 'U'):
                msg = 'Found unknown action in closed pos stream: %s.' % data
                self.logger.error(msg)
            else:
                self.logger.debug('Update data without action:')
                self.logger.debug(data)
                pos = self.closed_pos[trade_id]
                for field in data:
                    pos.__set_attribute__(field, data[field])

        if 'ClosedPosition' in self.add_callbacks:
            callbacks = self.add_callbacks['ClosedPosition']
            for func in callbacks:
                try:
                    callbacks[func](data)
                except:
                    self.logger.error('Call of %s raised an error:' % func)
                    self.logger.error(sys.exc_info()[0])
                    self.logger.error(sys.exc_info()[1])
                    self.logger.error(sys.exc_info()[2])

    def __on_error__(self, msg=''):
        self.logger.error('Error: %s' % msg)
        raise ServerError(msg)

    def __on_disconnect__(self, msg=''):
        self.bearer_token = None
        self.socket_id = None
        self.connection_status = 'unset'
        self.logger.info('Disconnected.')

    def __on_connect__(self, msg=''):
        self.connection_status = 'established'
        self.logger.info('Connection established.')

    def __on_connection_error__(self, msg=''):
        self.logger.error('Connection error: %s' % msg)
