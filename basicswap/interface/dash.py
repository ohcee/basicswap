#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2022-2024 tecnovert
# Copyright (c) 2024 The Basicswap developers
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

from .btc import BTCInterface
from basicswap.chainparams import Coins
from basicswap.util.address import decodeAddress
from basicswap.contrib.mnemonic import Mnemonic
from basicswap.contrib.test_framework.script import (
    CScript,
    OP_DUP,
    OP_HASH160,
    OP_EQUALVERIFY,
    OP_CHECKSIG,
)


class DASHInterface(BTCInterface):
    @staticmethod
    def coin_type():
        return Coins.DASH

    def __init__(self, coin_settings, network, swap_client=None):
        super().__init__(coin_settings, network, swap_client)
        self._wallet_passphrase = ""
        self._have_checked_seed = False

        self._wallet_v20_compatible = (
            False
            if not swap_client
            else swap_client.getChainClientSettings(self.coin_type()).get(
                "wallet_v20_compatible", False
            )
        )

    def decodeAddress(self, address: str) -> bytes:
        return decodeAddress(address)[1:]

    def getWalletSeedID(self) -> str:
        hdseed: str = self.rpc_wallet("dumphdinfo")["hdseed"]
        return self.getSeedHash(bytes.fromhex(hdseed)).hex()

    def entropyToMnemonic(self, key: bytes) -> None:
        return Mnemonic("english").to_mnemonic(key)

    def initialiseWallet(self, key_bytes: bytes, restore_time: int = -1) -> None:
        self._have_checked_seed = False
        if self._wallet_v20_compatible:
            self._log.warning("Generating wallet compatible with v20 seed.")
            words = self.entropyToMnemonic(key_bytes)
            mnemonic_passphrase = ""
            self.rpc_wallet(
                "upgradetohd", [words, mnemonic_passphrase, self._wallet_passphrase]
            )
            self._have_checked_seed = False
            if self._wallet_passphrase != "":
                self.unlockWallet(self._wallet_passphrase)
            return

        key_wif = self.encodeKey(key_bytes)
        self.rpc_wallet("sethdseed", [True, key_wif])

    def checkExpectedSeed(self, expect_seedid: str) -> bool:
        self._expect_seedid_hex = expect_seedid
        try:
            rv = self.rpc_wallet("dumphdinfo")
        except Exception as e:
            self._log.debug(f"DASH dumphdinfo failed {e}.")
            return False
        if rv["mnemonic"] != "":
            entropy = Mnemonic("english").to_entropy(rv["mnemonic"].split(" "))
            entropy_hash = self.getAddressHashFromKey(entropy)[::-1].hex()
            have_expected_seed: bool = expect_seedid == entropy_hash
        else:
            have_expected_seed: bool = expect_seedid == self.getWalletSeedID()
        self._have_checked_seed = True
        return have_expected_seed

    def withdrawCoin(self, value, addr_to, subfee):
        params = [addr_to, value, "", "", subfee, False, False, self._conf_target]
        return self.rpc_wallet("sendtoaddress", params)

    def getSpendableBalance(self) -> int:
        return self.make_int(self.rpc_wallet("getwalletinfo")["balance"])

    def getScriptForPubkeyHash(self, pkh: bytes) -> bytearray:
        # Return P2PKH
        return CScript([OP_DUP, OP_HASH160, pkh, OP_EQUALVERIFY, OP_CHECKSIG])

    def getBLockSpendTxFee(self, tx, fee_rate: int) -> int:
        add_bytes = 107
        size = len(tx.serialize_with_witness()) + add_bytes
        pay_fee = round(fee_rate * size / 1000)
        self._log.info(
            f"BLockSpendTx fee_rate, size, fee: {fee_rate}, {size}, {pay_fee}."
        )
        return pay_fee

    def findTxnByHash(self, txid_hex: str):
        # Only works for wallet txns
        try:
            rv = self.rpc_wallet("gettransaction", [txid_hex])
        except Exception as e:  # noqa: F841
            self._log.debug(
                "findTxnByHash getrawtransaction failed: {}".format(txid_hex)
            )
            return None
        if "confirmations" in rv and rv["confirmations"] >= self.blocks_confirmed:
            block_height = self.getBlockHeader(rv["blockhash"])["height"]
            return {"txid": txid_hex, "amount": 0, "height": block_height}

        return None

    def unlockWallet(self, password: str, check_seed: bool = True) -> None:
        super().unlockWallet(password, check_seed)
        if self._wallet_v20_compatible:
            # Store password for initialiseWallet
            self._wallet_passphrase = password

    def lockWallet(self):
        super().lockWallet()
        self._wallet_passphrase = ""

    def encryptWallet(
        self, old_password: str, new_password: str, check_seed: bool = True
    ):
        if old_password != "":
            self.unlockWallet(old_password, check_seed=False)
        seed_id_before: str = self.getWalletSeedID()

        self.rpc_wallet("encryptwallet", [new_password])

        if check_seed is False or seed_id_before == "Not found":
            return
        self.unlockWallet(new_password, check_seed=False)
        seed_id_after: str = self.getWalletSeedID()

        self.lockWallet()
        if seed_id_before == seed_id_after:
            return
        self._log.warning(f"{self.ticker()} wallet seed changed after encryption.")
        self._log.debug(
            f"seed_id_before: {seed_id_before} seed_id_after: {seed_id_after}."
        )
        self.setWalletSeedWarning(True)

    def changeWalletPassword(
        self, old_password: str, new_password: str, check_seed_if_encrypt: bool = True
    ):
        self._log.info("changeWalletPassword - {}".format(self.ticker()))
        if old_password == "":
            if self.isWalletEncrypted():
                raise ValueError("Old password must be set")
            return self.encryptWallet(old_password, new_password, check_seed_if_encrypt)
        self.rpc_wallet("walletpassphrasechange", [old_password, new_password])
