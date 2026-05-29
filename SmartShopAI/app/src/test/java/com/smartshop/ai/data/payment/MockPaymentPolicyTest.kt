package com.smartshop.ai.data.payment

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MockPaymentPolicyTest {
    @Test
    fun acceptsConfiguredMockPassword() {
        assertTrue(MockPaymentPolicy.accepts("123456"))
    }

    @Test
    fun rejectsWrongPassword() {
        assertFalse(MockPaymentPolicy.accepts("000000"))
        assertFalse(MockPaymentPolicy.accepts("12345"))
        assertFalse(MockPaymentPolicy.accepts("1234567"))
        assertFalse(MockPaymentPolicy.accepts("12a456"))
    }
}
