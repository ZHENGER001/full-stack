package com.smartshop.ai.data.model

data class RecognitionResult(
    val label: String,
    val confidence: Float,
    val relatedProducts: List<Product> = emptyList()
)
