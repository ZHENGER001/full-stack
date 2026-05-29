package com.smartshop.ai.data.payment

object MockPaymentPolicy {
    const val PASSWORD = "123456"

    fun accepts(password: String): Boolean =
        password == PASSWORD
}
