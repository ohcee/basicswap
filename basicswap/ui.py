# -*- coding: utf-8 -*-

# Copyright (c) 2020-2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

import json
from .util import (
    make_int,
    format_timestamp,
)
from .chainparams import (
    Coins,
)
from .basicswap_util import (
    TxLockTypes,
    DebugTypes,
    SwapTypes,
    BidStates,
    TxStates,
    TxTypes,
    strTxType,
    strBidState,
    strTxState,
    getLastBidState,
)

PAGE_LIMIT = 50


def tickerToCoinId(ticker):
    search_str = ticker.upper()
    for c in Coins:
        if c.name == search_str:
            return c.value
    raise ValueError('Unknown coin')


def getCoinType(coin_type_ind):
    # coin_type_ind can be int id or str ticker
    try:
        return int(coin_type_ind)
    except Exception:
        return tickerToCoinId(coin_type_ind)


def validateAmountString(amount, ci):
    if type(amount) != str:
        return
    ar = amount.split('.')
    if len(ar) > 1 and len(ar[1]) > ci.exp():
        raise ValueError('Too many decimal places in amount {}'.format(amount))


def inputAmount(amount_str, ci):
    validateAmountString(amount_str, ci)
    return make_int(amount_str, ci.exp())


def get_data_entry_or(post_data, name, default):
    if 'is_json' in post_data:
        return post_data.get(name, default)
    key_bytes = name.encode('utf-8')
    if key_bytes in post_data:
        return post_data[key_bytes][0].decode('utf-8')
    return default


def get_data_entry(post_data, name):
    if 'is_json' in post_data:
        return post_data[name]
    return post_data[name.encode('utf-8')][0].decode('utf-8')


def have_data_entry(post_data, name):
    if 'is_json' in post_data:
        return name in post_data
    return name.encode('utf-8') in post_data


def setCoinFilter(form_data, field_name):
    try:
        coin_type = getCoinType(get_data_entry(form_data, field_name))
    except Exception:
        return -1
    if coin_type == -1:
        return -1
    try:
        return Coins(coin_type)
    except Exception:
        raise ValueError('Unknown Coin Type {}'.format(str(field_name)))


def getTxIdHex(bid, tx_type, suffix):
    if tx_type == TxTypes.ITX:
        obj = bid.initiate_tx
    elif tx_type == TxTypes.PTX:
        obj = bid.participate_tx
    else:
        return 'Unknown Type'

    if not obj:
        return 'None'
    if not obj.txid:
        return 'None'
    return obj.txid.hex() + suffix


def getTxSpendHex(bid, tx_type):
    if tx_type == TxTypes.ITX:
        obj = bid.initiate_tx
    elif tx_type == TxTypes.PTX:
        obj = bid.participate_tx
    else:
        return 'Unknown Type'

    if not obj:
        return 'None'
    if not obj.spend_txid:
        return 'None'
    return obj.spend_txid.hex() + ' {}'.format(obj.spend_n)


def listBidStates():
    rv = []
    for s in BidStates:
        rv.append((int(s), strBidState(s)))
    return rv


def describeBid(swap_client, bid, xmr_swap, offer, xmr_offer, bid_events, edit_bid, show_txns, view_tx_ind=None, for_api=False, show_lock_transfers=False):
    ci_from = swap_client.ci(Coins(offer.coin_from))
    ci_to = swap_client.ci(Coins(offer.coin_to))
    ticker_from = ci_from.ticker()
    ticker_to = ci_to.ticker()

    state_description = ''
    if offer.swap_type == SwapTypes.SELLER_FIRST:
        if bid.state == BidStates.BID_SENT:
            state_description = 'Waiting for seller to accept.'
        elif bid.state == BidStates.BID_RECEIVED:
            state_description = 'Waiting for seller to accept.'
        elif bid.state == BidStates.BID_ACCEPTED:
            if not bid.initiate_tx:
                state_description = 'Waiting for seller to send initiate tx.'
            else:
                state_description = 'Waiting for initiate tx to confirm.'
        elif bid.state == BidStates.SWAP_INITIATED:
            state_description = 'Waiting for participate txn to be confirmed in {} chain'.format(ticker_to)
        elif bid.state == BidStates.SWAP_PARTICIPATING:
            if bid.was_sent:
                state_description = 'Waiting for participate txn to be spent in {} chain'.format(ticker_to)
            else:
                state_description = 'Waiting for initiate txn to be spent in {} chain'.format(ticker_from)
        elif bid.state == BidStates.SWAP_COMPLETED:
            state_description = 'Swap completed'
            if bid.getITxState() == TxStates.TX_REDEEMED and bid.getPTxState() == TxStates.TX_REDEEMED:
                state_description += ' successfully'
            else:
                state_description += ', ITX ' + strTxState(bid.getITxState()) + ', PTX ' + strTxState(bid.getPTxState())
        elif bid.state == BidStates.SWAP_TIMEDOUT:
            state_description = 'Timed out waiting for initiate txn'
        elif bid.state == BidStates.BID_ABANDONED:
            state_description = 'Bid abandoned'
        elif bid.state == BidStates.BID_ERROR:
            state_description = bid.state_note
    elif offer.swap_type == SwapTypes.XMR_SWAP:
        if bid.state == BidStates.BID_SENT:
            state_description = 'Waiting for offerer to accept'
        if bid.state == BidStates.BID_RECEIVING:
            # Offerer receiving bid from bidder
            state_description = 'Waiting for bid to be fully received'
        elif bid.state == BidStates.BID_RECEIVED:
            # Offerer received bid from bidder
            # TODO: Manual vs automatic
            state_description = 'Bid must be accepted'
        elif bid.state == BidStates.BID_RECEIVING_ACC:
            state_description = 'Receiving accepted bid message'
        elif bid.state == BidStates.BID_ACCEPTED:
            state_description = 'Offerer has accepted bid, waiting for bidder to respond'
        elif bid.state == BidStates.SWAP_DELAYING:
            last_state = getLastBidState(bid.states)
            if last_state == BidStates.BID_RECEIVED:
                state_description = 'Delaying before accepting bid'
            elif last_state == BidStates.BID_RECEIVING_ACC:
                state_description = 'Delaying before responding to accepted bid'
            elif last_state == BidStates.XMR_SWAP_SCRIPT_TX_REDEEMED:
                state_description = f'Delaying before spending from {ticker_to} lock tx'
            elif last_state == BidStates.BID_ACCEPTED:
                state_description = f'Delaying before sending {ticker_from} lock tx'
            else:
                state_description = 'Delaying before automated action'
        elif bid.state == BidStates.XMR_SWAP_HAVE_SCRIPT_COIN_SPEND_TX:
            state_description = f'Waiting for {ticker_from} lock tx to confirm in chain ({ci_from.blocks_confirmed} blocks)'
        elif bid.state == BidStates.XMR_SWAP_SCRIPT_COIN_LOCKED:
            if xmr_swap.b_lock_tx_id is None:
                state_description = f'Waiting for {ticker_to} lock tx'
            else:
                state_description = f'Waiting for {ticker_to} lock tx to confirm in chain ({ci_to.blocks_confirmed} blocks)'
        elif bid.state == BidStates.XMR_SWAP_NOSCRIPT_COIN_LOCKED:
            state_description = f'Waiting for offerer to unlock {ticker_from} lock tx'
        elif bid.state == BidStates.XMR_SWAP_LOCK_RELEASED:
            state_description = f'Waiting for bidder to spend from {ticker_from} lock tx'
        elif bid.state == BidStates.XMR_SWAP_SCRIPT_TX_REDEEMED:
            state_description = f'Waiting for offerer to spend from {ticker_to} lock tx'
        elif bid.state == BidStates.XMR_SWAP_NOSCRIPT_TX_REDEEMED:
            state_description = f'Waiting for {ticker_to} lock tx spend tx to confirm in chain'
        elif bid.state == BidStates.XMR_SWAP_SCRIPT_TX_PREREFUND:
            if bid.was_sent:
                state_description = f'Waiting for offerer to redeem or locktime to expire'
            else:
                state_description = f'Redeeming output'


    addr_label = swap_client.getAddressLabel([bid.bid_addr, ])[0]
    bid_rate = offer.rate if bid.rate is None else bid.rate

    data = {
        'coin_from': ci_from.coin_name(),
        'coin_to': ci_to.coin_name(),
        'amt_from': ci_from.format_amount(bid.amount),
        'amt_to': ci_to.format_amount((bid.amount * bid_rate) // ci_from.COIN()),
        'bid_rate': ci_to.format_amount(bid_rate),
        'ticker_from': ticker_from,
        'ticker_to': ticker_to,
        'bid_state': strBidState(bid.state),
        'state_description': state_description,
        'itx_state': strTxState(bid.getITxState()),
        'ptx_state': strTxState(bid.getPTxState()),
        'offer_id': bid.offer_id.hex(),
        'addr_from': bid.bid_addr,
        'addr_from_label': addr_label,
        'addr_fund_proof': bid.proof_address,
        'created_at': bid.created_at if for_api else format_timestamp(bid.created_at, with_seconds=True),
        'expired_at': bid.expire_at if for_api else format_timestamp(bid.expire_at, with_seconds=True),
        'was_sent': 'True' if bid.was_sent else 'False',
        'was_received': 'True' if bid.was_received else 'False',
        'initiate_tx': getTxIdHex(bid, TxTypes.ITX, ' ' + ticker_from),
        'initiate_conf': 'None' if (not bid.initiate_tx or not bid.initiate_tx.conf) else bid.initiate_tx.conf,
        'participate_tx': getTxIdHex(bid, TxTypes.PTX, ' ' + ticker_to),
        'participate_conf': 'None' if (not bid.participate_tx or not bid.participate_tx.conf) else bid.participate_tx.conf,
        'show_txns': show_txns,
        'can_abandon': True if bid.state not in (BidStates.BID_ABANDONED, BidStates.SWAP_COMPLETED) else False,
        'events': bid_events,
        'debug_ui': swap_client.debug_ui,
    }

    if edit_bid:
        data['bid_state_ind'] = int(bid.state)
        data['bid_states'] = listBidStates()

        if swap_client.debug_ui:
            data['debug_ind'] = bid.debug_ind
            data['debug_options'] = [(int(t), t.name) for t in DebugTypes]

    if show_txns:
        if offer.swap_type == SwapTypes.XMR_SWAP:
            txns = []
            if bid.xmr_a_lock_tx:
                confirms = None
                if swap_client.coin_clients[ci_from.coin_type()]['chain_height'] and bid.xmr_a_lock_tx.chain_height:
                    confirms = (swap_client.coin_clients[ci_from.coin_type()]['chain_height'] - bid.xmr_a_lock_tx.chain_height) + 1
                txns.append({'type': 'Chain A Lock', 'txid': bid.xmr_a_lock_tx.txid.hex(), 'confirms': confirms})
            if bid.xmr_a_lock_spend_tx:
                txns.append({'type': 'Chain A Lock Spend', 'txid': bid.xmr_a_lock_spend_tx.txid.hex()})
            if bid.xmr_b_lock_tx:
                confirms = None
                if swap_client.coin_clients[ci_to.coin_type()]['chain_height'] and bid.xmr_b_lock_tx.chain_height:
                    confirms = (swap_client.coin_clients[ci_to.coin_type()]['chain_height'] - bid.xmr_b_lock_tx.chain_height) + 1
                txns.append({'type': 'Chain B Lock', 'txid': bid.xmr_b_lock_tx.txid.hex(), 'confirms': confirms})
            if bid.xmr_b_lock_tx and bid.xmr_b_lock_tx.spend_txid:
                txns.append({'type': 'Chain B Lock Spend', 'txid': bid.xmr_b_lock_tx.spend_txid.hex()})
            if xmr_swap.a_lock_refund_tx:
                txns.append({'type': strTxType(TxTypes.XMR_SWAP_A_LOCK_REFUND), 'txid': xmr_swap.a_lock_refund_tx_id.hex()})
            if xmr_swap.a_lock_refund_spend_tx:
                txns.append({'type': strTxType(TxTypes.XMR_SWAP_A_LOCK_REFUND_SPEND), 'txid': xmr_swap.a_lock_refund_spend_tx_id.hex()})
            for tx_type, tx in bid.txns.items():
                if tx_type in (TxTypes.XMR_SWAP_A_LOCK_REFUND, TxTypes.XMR_SWAP_A_LOCK_REFUND_SPEND):
                    continue
                txns.append({'type': strTxType(tx_type), 'txid': tx.txid.hex()})
            data['txns'] = txns

            data['xmr_b_shared_address'] = ci_to.encodeSharedAddress(xmr_swap.pkbv, xmr_swap.pkbs) if xmr_swap.pkbs else None

            if swap_client.debug_ui:
                data['xmr_b_half_privatekey'] = ci_to.encodeKey(swap_client.getPathKey(offer.coin_from, offer.coin_to, bid.created_at, xmr_swap.contract_count, 2, True if offer.coin_to == Coins.XMR else False))

            if show_lock_transfers:
                if xmr_swap.pkbs:
                    data['lock_transfers'] = json.dumps(ci_to.showLockTransfers(xmr_swap.pkbv, xmr_swap.pkbs), indent=4)
                else:
                    data['lock_transfers'] = 'Shared address not yet known.'
        else:
            data['initiate_tx_refund'] = 'None' if not bid.initiate_txn_refund else bid.initiate_txn_refund.hex()
            data['participate_tx_refund'] = 'None' if not bid.participate_txn_refund else bid.participate_txn_refund.hex()
            data['initiate_tx_spend'] = getTxSpendHex(bid, TxTypes.ITX)
            data['participate_tx_spend'] = getTxSpendHex(bid, TxTypes.PTX)

            if bid.initiate_tx and bid.initiate_tx.tx_data is not None:
                data['initiate_tx_inputs'] = ci_from.listInputs(bid.initiate_tx.tx_data)
            if bid.participate_tx and bid.participate_tx.tx_data is not None:
                data['initiate_tx_inputs'] = ci_from.listInputs(bid.participate_tx.tx_data)

    if offer.swap_type == SwapTypes.XMR_SWAP:
        data['coin_a_lock_refund_tx_est_final'] = 'None'
        if bid.xmr_a_lock_tx and bid.xmr_a_lock_tx.block_time:
            if offer.lock_type == TxLockTypes.SEQUENCE_LOCK_TIME:
                raw_sequence = ci_from.getExpectedSequence(offer.lock_type, offer.lock_value)
                seconds_locked = ci_from.decodeSequence(raw_sequence)
                data['coin_a_lock_refund_tx_est_final'] = bid.xmr_a_lock_tx.block_time + seconds_locked
                data['coin_a_last_median_time'] = swap_client.coin_clients[offer.coin_from]['chain_median_time']

        if view_tx_ind:
            data['view_tx_ind'] = view_tx_ind
            view_tx_id = bytes.fromhex(view_tx_ind)

            if xmr_swap:
                if view_tx_id == xmr_swap.a_lock_tx_id and xmr_swap.a_lock_tx:
                    data['view_tx_hex'] = xmr_swap.a_lock_tx.hex()
                    data['chain_a_lock_tx_inputs'] = ci_from.listInputs(xmr_swap.a_lock_tx)
                if view_tx_id == xmr_swap.a_lock_refund_tx_id and xmr_swap.a_lock_refund_tx:
                    data['view_tx_hex'] = xmr_swap.a_lock_refund_tx.hex()
                if view_tx_id == xmr_swap.a_lock_refund_spend_tx_id and xmr_swap.a_lock_refund_spend_tx:
                    data['view_tx_hex'] = xmr_swap.a_lock_refund_spend_tx.hex()
                if view_tx_id == xmr_swap.a_lock_spend_tx_id and xmr_swap.a_lock_spend_tx:
                    data['view_tx_hex'] = xmr_swap.a_lock_spend_tx.hex()

                if 'view_tx_hex' in data:
                    data['view_tx_desc'] = json.dumps(ci_from.describeTx(data['view_tx_hex']), indent=4)

    return data
