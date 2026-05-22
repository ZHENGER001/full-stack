package com.smartshop.ai.data.model

data class User(
    val id: String = "user_001",
    val nickname: String = "购物达人",
    val avatar: String = "",
    val favorites: List<String> = emptyList(),
    val browsingHistory: List<String> = emptyList()
)
