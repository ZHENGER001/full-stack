package com.smartshop.ai.data.model

data class Category(
    val id: String,
    val name: String,
    val icon: String,
    val subcategories: List<Category> = emptyList()
)
