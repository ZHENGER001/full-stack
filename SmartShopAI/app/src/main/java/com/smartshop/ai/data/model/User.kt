package com.smartshop.ai.data.model

data class User(
    val id: String = "user_001",
    val username: String = "admin",
    val password: String = "admin123",
    val nickname: String = "管理员",
    val avatarUrl: String = "",
    val createdAt: String = "2026-05-30"
)
