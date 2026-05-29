package com.smartshop.ai.data.product

import android.content.Context
import android.net.Uri
import com.smartshop.ai.data.model.Category
import com.smartshop.ai.data.model.Product
import com.smartshop.ai.data.model.ProductReview
import com.smartshop.ai.data.model.ProductSku
import com.smartshop.ai.data.remote.SmartShopApi
import com.smartshop.ai.data.remote.toCategory
import com.smartshop.ai.data.remote.toProduct
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ProductRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: SmartShopApi
) {
    suspend fun getProducts(
        keyword: String? = null,
        category: String? = null,
        subcategory: String? = null,
        minPrice: Double? = null,
        maxPrice: Double? = null,
        sort: String? = null,
        limit: Int? = 500
    ): List<Product> {
        val localProducts = loadLocalProducts()
        val products = if (localProducts.isNotEmpty()) {
            localProducts
                .filterByKeyword(keyword)
                .filterByCategory(category)
                .filterBySubcategory(subcategory)
                .filter { product -> minPrice == null || product.price >= minPrice }
                .filter { product -> maxPrice == null || product.price <= maxPrice }
                .sortedBySort(sort)
                .let { products -> limit?.let(products::take) ?: products }
        } else {
            runCatching {
                api.getProducts(
                    keyword = keyword,
                    category = category,
                    subcategory = subcategory,
                    minPrice = minPrice,
                    maxPrice = maxPrice,
                    sort = sort,
                    limit = limit
                ).items.map { it.toProduct() }
            }.getOrElse { emptyList() }
        }
        cacheProducts(products)
        if (keyword == null && category == null && subcategory == null && minPrice == null && maxPrice == null) {
            cachedAllProducts = products
        }
        return products
    }

    suspend fun getProductDetail(productId: String): Product {
        val product = productCache[productId]
            ?: loadLocalProducts().firstOrNull { it.id == productId }
            ?: runCatching { api.getProductDetail(productId).toProduct() }
                .getOrElse { throw NoSuchElementException("商品不存在：$productId") }
        productCache[product.id] = product
        return product
    }

    suspend fun getProductSkus(productId: String): List<ProductSku> =
        getProductDetail(productId).skus

    suspend fun getProductReviews(productId: String): List<ProductReview> =
        getProductDetail(productId).reviews

    fun getCachedProduct(productId: String): Product? = productCache[productId]

    fun cachedProducts(): List<Product> = cachedAllProducts.ifEmpty { productCache.values.toList() }

    fun cachedCategories(): List<Category> = categoryCache

    suspend fun getCategories(): List<Category> {
        val categories = loadLocalProducts()
            .takeIf { it.isNotEmpty() }
            ?.let { products ->
                products
                .groupBy { it.category }
                .entries
                .mapIndexed { index, (category, products) ->
                    Category(
                        id = category,
                        name = category,
                        icon = listOf("美", "数", "衣", "食").getOrElse(index) { "品" },
                        subcategories = products.map { it.categoryId }
                            .distinct()
                            .map { subcategory -> Category(id = subcategory, name = subcategory, icon = "") }
                    )
                }
            }
            ?: runCatching {
                api.getCategories().categories.mapIndexed { index, item -> item.toCategory(index) }
            }.getOrElse { emptyList() }
        categoryCache = categories
        return categories
    }

    suspend fun searchProducts(query: String, category: String? = null): List<Product> {
        val products = loadLocalProducts()
            .takeIf { it.isNotEmpty() }
            ?.let {
                cacheProducts(it)
                searchCachedProducts(query, category)
            }
            ?: runCatching {
                api.searchProducts(query, category = category, limit = 500).items.map { it.toProduct() }
            }.getOrElse {
                searchCachedProducts(query, category)
            }
        cacheProducts(products)
        return products
    }

    fun searchCachedProducts(query: String, category: String? = null): List<Product> {
        val products = cachedProducts()
        val visibleProducts = products.filterByCategory(category)
        val normalizedQuery = query.trim()
        if (normalizedQuery.isBlank()) return visibleProducts

        val maxPrice = extractMaxPrice(normalizedQuery)
        val terms = expandLocalSearchTerms(normalizedQuery)
        return visibleProducts.asSequence()
            .filter { product -> maxPrice == null || product.price <= maxPrice }
            .mapNotNull { product ->
                val score = product.localSearchScore(normalizedQuery, terms)
                if (score > 0) product to score else null
            }
            .sortedWith(
                compareByDescending<Pair<Product, Int>> { it.second }
                    .thenByDescending { it.first.rating }
                    .thenBy { it.first.price }
            )
            .map { it.first }
            .toList()
    }

    private val productCache = mutableMapOf<String, Product>()
    private var cachedAllProducts: List<Product> = emptyList()
    private var categoryCache: List<Category> = emptyList()
    private var localProductCache: List<Product>? = null

    private fun cacheProducts(products: List<Product>) {
        products.forEach { productCache[it.id] = it }
    }

    private suspend fun loadLocalProducts(): List<Product> = withContext(Dispatchers.IO) {
        localProducts()
    }

    private fun localProducts(): List<Product> {
        localProductCache?.let { return it }
        return synchronized(this) {
            localProductCache?.let { return@synchronized it }
            val products = context.assets.list("")?.asSequence()
                .orEmpty()
                .flatMap { folder ->
                    context.assets.list("$folder/data")?.asSequence()
                        .orEmpty()
                        .filter { it.endsWith(".json") }
                        .map { file -> "$folder/data/$file" }
                }
                .mapNotNull(::readLocalProduct)
                .sortedByDescending { it.rating }
                .toList()
            localProductCache = products
            cacheProducts(products)
            if (products.isNotEmpty()) cachedAllProducts = products
            products
        }
    }

    private fun readLocalProduct(assetPath: String): Product? =
        runCatching {
            context.assets.open(assetPath).bufferedReader(Charsets.UTF_8).use { reader ->
                val json = JsonParser().parse(reader).asJsonObject
                val knowledge = json.getAsJsonObject("rag_knowledge")
                val productId = json.string("product_id")
                val basePrice = json.double("base_price") ?: 0.0
                val productSkus = json.arrayObjects("skus").mapIndexed { index, sku ->
                    val properties = sku.getAsJsonObject("properties")
                    val skuText = properties?.entrySet()
                        ?.joinToString(" / ") { entry -> "${entry.key}: ${entry.value.asString}" }
                        ?.takeIf { it.isNotBlank() }
                        ?: "默认规格"
                    val skuName = properties?.entrySet()
                        ?.joinToString(" / ") { entry -> entry.key }
                        ?.takeIf { it.isNotBlank() }
                        ?: "规格"
                    val price = sku.double("price") ?: basePrice
                    ProductSku(
                        id = sku.string("sku_id").ifBlank { "${productId}_sku_${index + 1}" },
                        productId = productId,
                        skuName = skuName,
                        skuText = skuText,
                        price = price,
                        originalPrice = null,
                        stock = sku.int("stock") ?: (20 + index * 3)
                    )
                }
                val faqs = knowledge.arrayObjects("official_faq")
                    .map { faq ->
                        "${faq.string("question")} ${faq.string("answer")}".compact(90)
                    }
                val reviewObjects = knowledge.arrayObjects("user_reviews")
                val productReviews = reviewObjects
                    .mapIndexed { index, review ->
                        ProductReview(
                            id = "${productId}_review_${index + 1}",
                            productId = productId,
                            userId = "mock_user_${index + 1}",
                            userName = review.string("nickname").ifBlank { "用户${index + 1}" },
                            userAvatar = "",
                            rating = review.double("rating")?.toFloat() ?: 5f,
                            content = review.string("content"),
                            skuText = productSkus.takeIf { it.isNotEmpty() }
                                ?.get(index % productSkus.size)
                                ?.skuText
                                ?: "默认规格",
                            createdAt = "2026-05-${(20 + index).toString().padStart(2, '0')}"
                        )
                    }
                val rating = reviewObjects
                    .mapNotNull { review -> review.double("rating")?.toFloat() }
                    .takeIf { values -> values.isNotEmpty() }
                    ?.average()
                    ?.toFloat()
                    ?: 0f
                val imageFileName = json.string("image_path")
                    .replace("\\", "/")
                    .substringAfterLast("/")
                val datasetFolder = assetPath.substringBefore("/data/")
                val imagePath = "$datasetFolder/images/$imageFileName"
                Product(
                    id = productId,
                    name = json.string("title"),
                    description = knowledge.string("marketing_description").compact(130),
                    price = basePrice,
                    originalPrice = null,
                    imageUrl = imagePath.toAndroidAssetUrl(),
                    category = json.string("category"),
                    categoryId = json.string("sub_category"),
                    brand = json.string("brand"),
                    rating = rating,
                    reviewCount = productReviews.size,
                    tags = listOf(json.string("category"), json.string("sub_category"))
                        .filter { tag -> tag.isNotBlank() },
                    specs = mapOf(
                        "品牌" to json.string("brand"),
                        "分类" to json.string("category"),
                        "销量" to "${productReviews.size * 38 + productSkus.size * 11}",
                        "SKU" to "${productSkus.size} 个",
                        "FAQ" to "${faqs.size} 条",
                        "库存" to productSkus.sumOf { it.stock }.toString()
                    ),
                    skus = productSkus,
                    reviews = productReviews,
                    faqSummaries = faqs,
                    reviewSummaries = productReviews.map { review ->
                        "${review.userName}：${review.content}".compact(90)
                    },
                    skuSummaries = productSkus.map { sku ->
                        "${sku.skuText} ¥${"%.0f".format(sku.price)} 库存${sku.stock}"
                    },
                    aiComment = knowledge.string("marketing_description").compact(120),
                    inStock = productSkus.any { it.stock > 0 }
                )
            }
        }.getOrNull()

    private fun List<Product>.filterByCategory(category: String?): List<Product> {
        if (category.isNullOrBlank()) return this
        return filter { product -> product.categoryId == category || product.category == category }
    }

    private fun List<Product>.filterBySubcategory(subcategory: String?): List<Product> {
        if (subcategory.isNullOrBlank()) return this
        return filter { product -> product.categoryId == subcategory }
    }

    private fun List<Product>.filterByKeyword(keyword: String?): List<Product> {
        if (keyword.isNullOrBlank()) return this
        val terms = expandLocalSearchTerms(keyword)
        return filter { product -> product.localSearchScore(keyword, terms) > 0 }
    }

    private fun List<Product>.sortedBySort(sort: String?): List<Product> = when (sort) {
        "price_asc" -> sortedBy { it.price }
        "price_desc" -> sortedByDescending { it.price }
        else -> sortedByDescending { it.rating }
    }

    private fun expandLocalSearchTerms(query: String): List<String> {
        val lowerQuery = query.lowercase()
        val terms = linkedSetOf<String>()
        terms += lowerQuery

        searchSynonyms.forEach { group ->
            if (group.any { lowerQuery.contains(it) }) {
                terms += group
            }
        }

        lowerQuery.split(searchSeparators)
            .map { it.trim() }
            .filter { term -> term.length >= 2 && term !in searchStopWords && term.toDoubleOrNull() == null }
            .forEach { terms += it }

        return terms.filter { it.isNotBlank() }
    }

    private fun Product.localSearchScore(query: String, terms: List<String>): Int {
        val lowerQuery = query.lowercase()
        val searchableText = buildString {
            append(name).append(' ')
            append(brand).append(' ')
            append(category).append(' ')
            append(categoryId).append(' ')
            append(description).append(' ')
            append(tags.joinToString(" ")).append(' ')
            append(specs.values.joinToString(" ")).append(' ')
            append(skuSummaries.joinToString(" ")).append(' ')
            append(faqSummaries.joinToString(" ")).append(' ')
            append(reviewSummaries.joinToString(" "))
        }.lowercase()

        var score = 0
        if (name.lowercase().contains(lowerQuery)) score += 30
        if (brand.lowercase().contains(lowerQuery)) score += 20
        if (category.lowercase().contains(lowerQuery) || categoryId.lowercase().contains(lowerQuery)) score += 16
        if (searchableText.contains(lowerQuery)) score += 12

        terms.forEach { term ->
            if (name.lowercase().contains(term)) score += 10
            if (brand.lowercase().contains(term)) score += 7
            if (category.lowercase().contains(term) || categoryId.lowercase().contains(term)) score += 6
            if (tags.any { it.lowercase().contains(term) }) score += 5
            if (description.lowercase().contains(term)) score += 4
            if (skuSummaries.any { it.lowercase().contains(term) }) score += 3
            if (faqSummaries.any { it.lowercase().contains(term) }) score += 3
            if (reviewSummaries.any { it.lowercase().contains(term) }) score += 3
            if (specs.values.any { it.lowercase().contains(term) }) score += 2
        }
        return score
    }

    private fun extractMaxPrice(query: String): Double? {
        val underPrice = Regex("""(\d+(?:\.\d+)?)\s*元?\s*(以下|以内|内)""").find(query)
            ?.groupValues
            ?.getOrNull(1)
            ?.toDoubleOrNull()
        if (underPrice != null) return underPrice

        return Regex("""(低于|不超过|小于|少于)\s*(\d+(?:\.\d+)?)""").find(query)
            ?.groupValues
            ?.getOrNull(2)
            ?.toDoubleOrNull()
    }

    private companion object {
        val searchSeparators = Regex("""[\s,，。.!！?？、;；:：/\\|（）()\[\]{}"']+""")
        val searchStopWords = setOf(
            "推荐",
            "一款",
            "适合",
            "有哪些",
            "有没有",
            "帮我",
            "类似",
            "同款",
            "以下",
            "以内",
            "低于",
            "不超过",
            "价格",
            "商品"
        )
        val searchSynonyms = listOf(
            listOf("洗面奶", "洁面", "洁面乳", "洁面膏"),
            listOf("油皮", "控油", "清爽", "油性肌肤"),
            listOf("蓝牙耳机", "蓝牙", "耳机", "无线耳机"),
            listOf("手机", "智能手机", "5g"),
            listOf("外套", "夹克", "上衣"),
            listOf("跑步", "运动", "训练"),
            listOf("便宜", "平价", "低价", "实惠")
        )
    }
}

private fun JsonObject.string(name: String): String =
    get(name)?.takeIf { !it.isJsonNull }?.asString.orEmpty()

private fun JsonObject.double(name: String): Double? =
    get(name)?.takeIf { !it.isJsonNull }?.asDouble

private fun JsonObject.int(name: String): Int? =
    get(name)?.takeIf { !it.isJsonNull }?.asInt

private fun JsonObject.arrayObjects(name: String): List<JsonObject> =
    getAsJsonArray(name)?.mapNotNull { element: JsonElement ->
        element.takeIf { !it.isJsonNull && it.isJsonObject }?.asJsonObject
    }.orEmpty()

private fun String.compact(maxLength: Int): String {
    val text = trim().replace(Regex("\\s+"), " ")
    return if (text.length <= maxLength) text else "${text.take(maxLength).trimEnd()}..."
}

private fun String.toAndroidAssetUrl(): String =
    "file:///android_asset/" + replace("\\", "/")
        .split("/")
        .joinToString("/") { segment -> Uri.encode(segment) }
