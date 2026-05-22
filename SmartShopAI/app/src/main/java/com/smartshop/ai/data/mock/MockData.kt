package com.smartshop.ai.data.mock

import com.smartshop.ai.data.model.*

object MockData {

    // ==================== 商品数据 ====================

    val products = listOf(
        Product(
            id = "p001",
            name = "索尼 WH-1000XM5 无线降噪头戴式耳机",
            description = "索尼旗舰级主动降噪耳机，搭载全新V1集成处理器，30小时超长续航，支持LDAC高解析度音频传输，佩戴舒适轻盈，智能免摘对话功能，商务通勤必备之选。",
            price = 2299.0,
            originalPrice = 2999.0,
            imageUrl = "https://picsum.photos/seed/headphone1/400/400",
            images = listOf(
                "https://picsum.photos/seed/headphone1a/400/400",
                "https://picsum.photos/seed/headphone1b/400/400",
                "https://picsum.photos/seed/headphone1c/400/400"
            ),
            category = "数码电子",
            categoryId = "cat_01",
            brand = "索尼",
            rating = 4.8f,
            reviewCount = 12580,
            tags = listOf("降噪", "头戴式", "蓝牙", "高音质", "长续航"),
            specs = mapOf(
                "类型" to "头戴式无线降噪耳机",
                "降噪技术" to "自适应主动降噪",
                "续航时间" to "30小时",
                "蓝牙版本" to "5.2",
                "重量" to "250g",
                "充电接口" to "USB-C"
            ),
            aiComment = "这款耳机在降噪和音质方面都是业界标杆，特别适合通勤和差旅使用。续航30小时基本一周一充，LDAC编码让蓝牙也能享受高品质音乐。"
        ),
        Product(
            id = "p002",
            name = "华为 Mate 60 Pro 智能手机",
            description = "搭载麒麟9000S芯片，支持卫星通话功能，XMAGE影像系统带来专业级拍照体验，6.82英寸LTPO OLED曲面屏，5000mAh大电池，88W有线快充。",
            price = 6999.0,
            originalPrice = 6999.0,
            imageUrl = "https://picsum.photos/seed/phone1/400/400",
            images = listOf(
                "https://picsum.photos/seed/phone1a/400/400",
                "https://picsum.photos/seed/phone1b/400/400",
                "https://picsum.photos/seed/phone1c/400/400"
            ),
            category = "数码电子",
            categoryId = "cat_01",
            brand = "华为",
            rating = 4.9f,
            reviewCount = 35420,
            tags = listOf("5G", "旗舰", "拍照", "卫星通话", "国产"),
            specs = mapOf(
                "处理器" to "麒麟9000S",
                "屏幕" to "6.82英寸 LTPO OLED",
                "存储" to "12GB+512GB",
                "电池" to "5000mAh",
                "快充" to "88W有线 / 50W无线",
                "影像" to "5000万像素三摄"
            ),
            aiComment = "华为年度旗舰，卫星通话是最大亮点，影像系统也非常出色。如果你看重国产生态和通信能力，这款非常值得入手。"
        ),
        Product(
            id = "p003",
            name = "苹果 MacBook Air 15英寸 M3芯片",
            description = "全新M3芯片带来强劲性能，15.3英寸Liquid Retina显示屏，18小时超长续航，无风扇静音设计，仅重1.51kg，支持MagSafe磁吸充电，适合创意工作者和学生。",
            price = 10499.0,
            originalPrice = 10999.0,
            imageUrl = "https://picsum.photos/seed/laptop1/400/400",
            images = listOf(
                "https://picsum.photos/seed/laptop1a/400/400",
                "https://picsum.photos/seed/laptop1b/400/400",
                "https://picsum.photos/seed/laptop1c/400/400"
            ),
            category = "数码电子",
            categoryId = "cat_01",
            brand = "苹果",
            rating = 4.7f,
            reviewCount = 8920,
            tags = listOf("轻薄", "高性能", "大屏", "长续航", "静音"),
            specs = mapOf(
                "芯片" to "Apple M3",
                "屏幕" to "15.3英寸 Liquid Retina",
                "内存" to "16GB统一内存",
                "存储" to "512GB SSD",
                "续航" to "18小时",
                "重量" to "1.51kg"
            ),
            aiComment = "大屏轻薄本的标杆之作，M3芯片日常使用绰绰有余，18小时续航让你告别电量焦虑。无风扇设计在图书馆或咖啡厅使用完全没有噪音。"
        ),
        Product(
            id = "p004",
            name = "Apple Watch Ultra 2 智能手表",
            description = "钛金属表壳，49mm超大表盘，双频GPS精准定位，水深计和水温传感器支持潜水，3000尼特超亮屏幕，36小时续航，户外运动爱好者的终极装备。",
            price = 5999.0,
            originalPrice = 6499.0,
            imageUrl = "https://picsum.photos/seed/watch1/400/400",
            images = listOf(
                "https://picsum.photos/seed/watch1a/400/400",
                "https://picsum.photos/seed/watch1b/400/400"
            ),
            category = "数码电子",
            categoryId = "cat_01",
            brand = "苹果",
            rating = 4.6f,
            reviewCount = 5230,
            tags = listOf("智能手表", "运动", "户外", "潜水", "钛金属"),
            specs = mapOf(
                "表壳材质" to "钛金属",
                "表盘尺寸" to "49mm",
                "防水等级" to "100米",
                "续航" to "36小时",
                "屏幕亮度" to "3000尼特",
                "定位" to "双频精密GPS"
            ),
            aiComment = "如果你热爱户外运动，这绝对是目前最强的智能手表。钛金属耐造，双频GPS定位精准，潜水功能也很专业。唯一缺点是只能配合iPhone使用。"
        ),
        Product(
            id = "p005",
            name = "德龙 全自动意式咖啡机 ECAM450.76",
            description = "一键萃取意式浓缩、美式、卡布奇诺等多种咖啡，LatteCrema自动奶泡系统，触控彩屏操作，可存储个人配方，内置静音研磨器，在家享受咖啡馆级别体验。",
            price = 4599.0,
            originalPrice = 5999.0,
            imageUrl = "https://picsum.photos/seed/coffee1/400/400",
            images = listOf(
                "https://picsum.photos/seed/coffee1a/400/400",
                "https://picsum.photos/seed/coffee1b/400/400"
            ),
            category = "家居生活",
            categoryId = "cat_02",
            brand = "德龙",
            rating = 4.7f,
            reviewCount = 6780,
            tags = listOf("咖啡机", "全自动", "意式", "奶泡", "家用"),
            specs = mapOf(
                "类型" to "全自动意式咖啡机",
                "压力" to "15bar",
                "水箱容量" to "1.8L",
                "豆仓容量" to "300g",
                "奶泡系统" to "LatteCrema全自动",
                "功率" to "1450W"
            ),
            aiComment = "咖啡爱好者的居家神器，LatteCrema奶泡系统打出的奶泡绵密细腻，触控屏操作非常方便。虽然价格不便宜，但比每天去咖啡馆划算多了。"
        ),
        Product(
            id = "p006",
            name = "石头 G20 扫拖机器人",
            description = "搭载RR Mason 10.0算法，精准避障不缠绕，声波震动拖地模块，自动集尘+自清洁基站，5500Pa大吸力，智能分区清扫，解放双手的清洁好帮手。",
            price = 3799.0,
            originalPrice = 4299.0,
            imageUrl = "https://picsum.photos/seed/vacuum1/400/400",
            images = listOf(
                "https://picsum.photos/seed/vacuum1a/400/400",
                "https://picsum.photos/seed/vacuum1b/400/400"
            ),
            category = "家居生活",
            categoryId = "cat_02",
            brand = "石头科技",
            rating = 4.8f,
            reviewCount = 21350,
            tags = listOf("扫地机器人", "扫拖一体", "自动集尘", "智能避障", "自清洁"),
            specs = mapOf(
                "吸力" to "5500Pa",
                "避障" to "3D结构光+红外",
                "拖地" to "声波震动拖布",
                "基站功能" to "自动集尘+自清洁+烘干",
                "续航" to "180分钟",
                "噪音" to "≤67dB"
            ),
            aiComment = "石头G20是目前扫拖机器人的天花板级产品，避障能力强，拖地效果好，基站功能齐全。养宠物家庭特别推荐，再也不用担心扫地机推着宠物便便满屋跑了。"
        ),
        Product(
            id = "p007",
            name = "小米空气净化器4 Pro",
            description = "CADR值500m³/h，高效过滤PM2.5、甲醛和过敏原，OLED触控显示屏实时显示空气质量，米家App远程控制，静音模式低至32.1dB，适合卧室和客厅。",
            price = 1499.0,
            originalPrice = 1799.0,
            imageUrl = "https://picsum.photos/seed/purifier1/400/400",
            images = listOf(
                "https://picsum.photos/seed/purifier1a/400/400",
                "https://picsum.photos/seed/purifier1b/400/400"
            ),
            category = "家居生活",
            categoryId = "cat_02",
            brand = "小米",
            rating = 4.5f,
            reviewCount = 18900,
            tags = listOf("空气净化器", "除甲醛", "除PM2.5", "静音", "智能"),
            specs = mapOf(
                "CADR" to "500m³/h",
                "适用面积" to "35-60㎡",
                "滤芯寿命" to "6-12个月",
                "噪音" to "32.1-64.3dB",
                "功率" to "50W",
                "连接" to "WiFi / 米家App"
            ),
            aiComment = "小米空净性价比之王，CADR值500在这个价位非常能打。特别适合新装修房子或者雾霾天使用，静音模式几乎听不到声音，放卧室也不影响睡眠。"
        ),
        Product(
            id = "p008",
            name = "Yeelight 智能护眼台灯 Pro",
            description = "Ra98高显色指数，模拟太阳光谱，无频闪无蓝光危害，支持米家/HomeKit双平台，亮度色温无极调节，番茄钟专注模式，学生和办公族的护眼之选。",
            price = 499.0,
            originalPrice = 599.0,
            imageUrl = "https://picsum.photos/seed/lamp1/400/400",
            images = listOf(
                "https://picsum.photos/seed/lamp1a/400/400",
                "https://picsum.photos/seed/lamp1b/400/400"
            ),
            category = "家居生活",
            categoryId = "cat_02",
            brand = "Yeelight",
            rating = 4.6f,
            reviewCount = 9450,
            tags = listOf("台灯", "护眼", "智能", "无频闪", "学生"),
            specs = mapOf(
                "显色指数" to "Ra98",
                "色温范围" to "2700K-6500K",
                "照度" to "国AA级",
                "智能平台" to "米家 / Apple HomeKit",
                "功率" to "14W",
                "频闪" to "无可视频闪"
            ),
            aiComment = "Ra98的高显色在台灯里非常少见，色彩还原度极高。番茄钟模式很适合备考学生，到时间自动变暗提醒休息。护眼效果值得信赖。"
        ),
        Product(
            id = "p009",
            name = "耐克 Air Max 270 React 运动鞋",
            description = "经典Air Max气垫与React泡棉双重缓震，透气网面鞋身，后跟大面积可视气垫，百搭配色适合日常穿搭，无论跑步还是逛街都轻松舒适。",
            price = 899.0,
            originalPrice = 1299.0,
            imageUrl = "https://picsum.photos/seed/sneaker1/400/400",
            images = listOf(
                "https://picsum.photos/seed/sneaker1a/400/400",
                "https://picsum.photos/seed/sneaker1b/400/400",
                "https://picsum.photos/seed/sneaker1c/400/400"
            ),
            category = "时尚穿搭",
            categoryId = "cat_03",
            brand = "耐克",
            rating = 4.5f,
            reviewCount = 14200,
            tags = listOf("运动鞋", "气垫", "缓震", "透气", "百搭"),
            specs = mapOf(
                "鞋底技术" to "Air Max 270 + React",
                "鞋面材质" to "透气网布+合成材料",
                "适用场景" to "跑步/日常/休闲",
                "闭合方式" to "系带",
                "产地" to "越南"
            ),
            aiComment = "Air Max 270 React是耐克最舒服的日常鞋款之一，双重缓震脚感软弹，270大气垫回头率很高。当前折扣力度不错，比原价省了400块。"
        ),
        Product(
            id = "p010",
            name = "小米城市通勤双肩背包",
            description = "30L大容量，可容纳15.6英寸笔记本，防泼水面料不惧小雨，隐藏式防盗口袋，人体工学背负系统减轻肩部压力，多功能分区收纳井井有条。",
            price = 249.0,
            originalPrice = 349.0,
            imageUrl = "https://picsum.photos/seed/backpack1/400/400",
            images = listOf(
                "https://picsum.photos/seed/backpack1a/400/400",
                "https://picsum.photos/seed/backpack1b/400/400"
            ),
            category = "时尚穿搭",
            categoryId = "cat_03",
            brand = "小米",
            rating = 4.4f,
            reviewCount = 22100,
            tags = listOf("双肩包", "通勤", "防水", "大容量", "商务"),
            specs = mapOf(
                "容量" to "30L",
                "材质" to "防泼水涤纶",
                "电脑仓" to "最大15.6英寸",
                "重量" to "0.75kg",
                "尺寸" to "48×34×17cm"
            ),
            aiComment = "小米这款背包是通勤性价比之选，249块的价格做工扎实，防泼水面料下雨天也不慌。隐藏防盗口袋放手机钱包很安心，30L容量日常通勤绰绰有余。"
        ),
        Product(
            id = "p011",
            name = "SK-II 神仙水护肤精华露 230ml",
            description = "蕴含超过90%的PITERA精华，改善肌肤纹理，提亮肤色，收缩毛孔，持续使用让肌肤呈现水润透亮的健康光泽，全球销量领先的明星护肤单品。",
            price = 1190.0,
            originalPrice = 1590.0,
            imageUrl = "https://picsum.photos/seed/skincare1/400/400",
            images = listOf(
                "https://picsum.photos/seed/skincare1a/400/400",
                "https://picsum.photos/seed/skincare1b/400/400"
            ),
            category = "美妆护肤",
            categoryId = "cat_04",
            brand = "SK-II",
            rating = 4.7f,
            reviewCount = 45600,
            tags = listOf("护肤", "精华", "保湿", "提亮", "抗老"),
            specs = mapOf(
                "容量" to "230ml",
                "核心成分" to "PITERA精华",
                "适用肤质" to "所有肤质",
                "产地" to "日本",
                "保质期" to "3年"
            ),
            aiComment = "SK-II神仙水是护肤界的经典神话，PITERA成分确实对改善肤质有明显效果。建议先买小样试试是否适合自己，如果肤质合适长期用效果很好。现在活动价比平时便宜不少。"
        ),
        Product(
            id = "p012",
            name = "Manduka PRO 专业瑜伽垫 6mm",
            description = "德国制造，采用闭孔表面技术防止汗水渗透，高密度缓冲保护关节，防滑纹理增强抓地力，终身质保，专业瑜伽爱好者和教练的首选。",
            price = 899.0,
            originalPrice = 1099.0,
            imageUrl = "https://picsum.photos/seed/yogamat1/400/400",
            images = listOf(
                "https://picsum.photos/seed/yogamat1a/400/400",
                "https://picsum.photos/seed/yogamat1b/400/400"
            ),
            category = "运动户外",
            categoryId = "cat_05",
            brand = "Manduka",
            rating = 4.8f,
            reviewCount = 3560,
            tags = listOf("瑜伽垫", "专业", "防滑", "环保", "高密度"),
            specs = mapOf(
                "厚度" to "6mm",
                "材质" to "闭孔PVC",
                "尺寸" to "180×66cm",
                "重量" to "3.4kg",
                "产地" to "德国",
                "质保" to "终身质保"
            ),
            aiComment = "Manduka PRO是瑜伽垫中的爱马仕，闭孔技术不吸汗不发臭，高密度对膝盖友好。虽然价格偏高，但终身质保意味着一次投资长期使用，练瑜伽认真的话非常推荐。"
        ),
        Product(
            id = "p013",
            name = "漫步者 LolliPods Pro 2 真无线降噪耳机",
            description = "42dB深度主动降噪，LDAC高清音质，蓝牙5.3稳定连接，单次续航6小时，配合充电盒总续航28小时，IP54防水防尘，通透模式自然通话。",
            price = 399.0,
            originalPrice = 499.0,
            imageUrl = "https://picsum.photos/seed/earbuds1/400/400",
            images = listOf(
                "https://picsum.photos/seed/earbuds1a/400/400",
                "https://picsum.photos/seed/earbuds1b/400/400"
            ),
            category = "数码电子",
            categoryId = "cat_01",
            brand = "漫步者",
            rating = 4.4f,
            reviewCount = 28700,
            tags = listOf("真无线", "降噪", "蓝牙耳机", "高性价比", "LDAC"),
            specs = mapOf(
                "类型" to "入耳式真无线降噪耳机",
                "降噪深度" to "42dB",
                "续航" to "单次6h / 总28h",
                "蓝牙版本" to "5.3",
                "防水等级" to "IP54",
                "编码" to "LDAC/AAC/SBC"
            ),
            aiComment = "400元价位段的降噪耳机卷王，42dB降噪深度超越不少千元耳机，LDAC编码音质也不错。预算有限又想体验降噪的话，这款是最佳选择之一。"
        ),
        Product(
            id = "p014",
            name = "小米14 Ultra 影像旗舰手机",
            description = "搭载骁龙8 Gen3处理器，与徕卡深度合作Summilux光学镜头，一英寸主摄传感器，支持4K120fps视频录制，IP68防水，5300mAh电池+90W快充。",
            price = 5999.0,
            originalPrice = 6499.0,
            imageUrl = "https://picsum.photos/seed/phone2/400/400",
            images = listOf(
                "https://picsum.photos/seed/phone2a/400/400",
                "https://picsum.photos/seed/phone2b/400/400",
                "https://picsum.photos/seed/phone2c/400/400"
            ),
            category = "数码电子",
            categoryId = "cat_01",
            brand = "小米",
            rating = 4.8f,
            reviewCount = 16800,
            tags = listOf("影像旗舰", "徕卡", "骁龙8Gen3", "一英寸大底", "5G"),
            specs = mapOf(
                "处理器" to "骁龙8 Gen3",
                "屏幕" to "6.73英寸 2K LTPO AMOLED",
                "存储" to "16GB+512GB",
                "主摄" to "5000万像素 1英寸大底",
                "电池" to "5300mAh + 90W快充",
                "防水" to "IP68"
            ),
            aiComment = "小米14 Ultra是目前安卓阵营最强的拍照手机之一，一英寸大底+徕卡调色出片质感很棒。骁龙8 Gen3性能拉满，5300mAh大电池续航也有保障，影像发烧友首选。"
        )
    )

    // ==================== 分类数据 ====================

    val categories = listOf(
        Category(
            id = "cat_01",
            name = "数码电子",
            icon = "🔌",
            subcategories = listOf(
                Category(id = "cat_01_01", name = "手机", icon = "📱"),
                Category(id = "cat_01_02", name = "耳机", icon = "🎧"),
                Category(id = "cat_01_03", name = "笔记本电脑", icon = "💻"),
                Category(id = "cat_01_04", name = "智能手表", icon = "⌚")
            )
        ),
        Category(
            id = "cat_02",
            name = "家居生活",
            icon = "🏠",
            subcategories = listOf(
                Category(id = "cat_02_01", name = "厨房电器", icon = "☕"),
                Category(id = "cat_02_02", name = "清洁电器", icon = "🧹"),
                Category(id = "cat_02_03", name = "空气净化", icon = "🌬"),
                Category(id = "cat_02_04", name = "智能照明", icon = "💡")
            )
        ),
        Category(
            id = "cat_03",
            name = "时尚穿搭",
            icon = "👗",
            subcategories = listOf(
                Category(id = "cat_03_01", name = "运动鞋", icon = "👟"),
                Category(id = "cat_03_02", name = "箱包", icon = "🎒"),
                Category(id = "cat_03_03", name = "服饰", icon = "👔")
            )
        ),
        Category(
            id = "cat_04",
            name = "美妆护肤",
            icon = "💄",
            subcategories = listOf(
                Category(id = "cat_04_01", name = "护肤", icon = "🧴"),
                Category(id = "cat_04_02", name = "彩妆", icon = "💋"),
                Category(id = "cat_04_03", name = "香水", icon = "🌸")
            )
        ),
        Category(
            id = "cat_05",
            name = "运动户外",
            icon = "🏃",
            subcategories = listOf(
                Category(id = "cat_05_01", name = "瑜伽", icon = "🧘"),
                Category(id = "cat_05_02", name = "跑步", icon = "🏃"),
                Category(id = "cat_05_03", name = "露营", icon = "⛺")
            )
        ),
        Category(
            id = "cat_06",
            name = "食品生鲜",
            icon = "🍎",
            subcategories = listOf(
                Category(id = "cat_06_01", name = "水果", icon = "🍇"),
                Category(id = "cat_06_02", name = "零食", icon = "🍪"),
                Category(id = "cat_06_03", name = "饮品", icon = "🧃")
            )
        )
    )

    // ==================== 轮播图数据 ====================

    val banners = listOf(
        Banner(
            id = "banner_01",
            title = "618年中大促",
            subtitle = "数码家电低至5折起",
            imageUrl = "https://picsum.photos/seed/banner1/800/400",
            backgroundColor = 0xFFFF6B6B
        ),
        Banner(
            id = "banner_02",
            title = "AI智能推荐",
            subtitle = "让购物更懂你的心",
            imageUrl = "https://picsum.photos/seed/banner2/800/400",
            backgroundColor = 0xFF4ECDC4
        ),
        Banner(
            id = "banner_03",
            title = "新品首发季",
            subtitle = "抢先体验前沿科技好物",
            imageUrl = "https://picsum.photos/seed/banner3/800/400",
            backgroundColor = 0xFF6C5CE7
        )
    )

    // ==================== 快捷提问建议 ====================

    val quickSuggestions = listOf(
        "推荐一款500元以内的蓝牙耳机",
        "最近有什么值得买的手机",
        "帮我挑一个送女朋友的礼物",
        "性价比高的笔记本电脑推荐"
    )

    // ==================== AI对话响应 ====================

    fun getAiResponse(userMessage: String): ChatMessage {
        val message = userMessage.lowercase()

        return when {
            // 耳机相关
            message.contains("耳机") || message.contains("headphone") || message.contains("蓝牙") -> {
                val recommendations = products.filter {
                    it.tags.any { tag -> tag.contains("耳机") || tag.contains("降噪") || tag.contains("真无线") }
                }.take(3)

                ChatMessage(
                    content = "关于耳机，我为你精选了几款不同价位的好产品：\n\n" +
                            "如果预算充足追求极致降噪和音质，推荐索尼WH-1000XM5，降噪和音质都是行业标杆；" +
                            "如果预算在500以内，漫步者LolliPods Pro 2性价比超高，42dB降噪深度碾压同价位。\n\n" +
                            "你更看重哪方面呢？降噪、音质还是性价比？我可以帮你进一步筛选。",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 手机相关
            message.contains("手机") || message.contains("phone") || message.contains("手机") -> {
                val recommendations = products.filter {
                    it.tags.any { tag -> tag.contains("旗舰") || tag.contains("5G") || tag.contains("拍照") }
                }.take(3)

                ChatMessage(
                    content = "最近值得关注的手机有这几款：\n\n" +
                            "📱 华为Mate 60 Pro - 卫星通话是独家亮点，影像和信号都很强，支持国产首选；\n" +
                            "📱 小米14 Ultra - 影像旗舰，一英寸大底+徕卡调色，拍照发烧友必看。\n\n" +
                            "你的预算大概在什么范围？主要看重拍照、性能还是续航？告诉我需求我帮你精准匹配。",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 笔记本电脑
            message.contains("笔记本") || message.contains("电脑") || message.contains("laptop") -> {
                val recommendations = listOf(
                    products.first { it.id == "p003" },
                    products.first { it.id == "p002" },
                    products.first { it.id == "p010" }
                )

                ChatMessage(
                    content = "笔记本电脑推荐要看你的用途：\n\n" +
                            "💻 日常办公+轻度创作：MacBook Air 15 M3，轻薄长续航，无风扇静音；\n" +
                            "💻 如果预算有限，也可以关注一些国产品牌的高性价比机型。\n\n" +
                            "你主要用来做什么呢？办公、编程、剪视频还是打游戏？不同用途推荐差异很大。",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 送礼相关
            message.contains("礼物") || message.contains("送") || message.contains("女朋友") || message.contains("男朋友") -> {
                val recommendations = listOf(
                    products.first { it.id == "p011" },
                    products.first { it.id == "p001" },
                    products.first { it.id == "p008" }
                )

                ChatMessage(
                    content = "送礼我有几个好建议：\n\n" +
                            "🎁 送女朋友：SK-II神仙水是经典不出错的选择，现在活动价很划算；\n" +
                            "🎁 送数码爱好者：索尼WH-1000XM5降噪耳机，实用又有品质感；\n" +
                            "🎁 送学生党：Yeelight护眼台灯，贴心又实用。\n\n" +
                            "可以告诉我送礼对象和预算，我帮你量身推荐！",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 推荐/好物
            message.contains("推荐") || message.contains("值得买") || message.contains("好物") -> {
                val recommendations = listOf(
                    products.first { it.id == "p006" },
                    products.first { it.id == "p013" },
                    products.first { it.id == "p009" }
                )

                ChatMessage(
                    content = "最近这几款产品口碑和销量都很好，值得关注：\n\n" +
                            "🔥 石头G20扫拖机器人 - 解放双手神器，自动集尘+自清洁；\n" +
                            "🔥 漫步者LolliPods Pro 2 - 400元价位降噪天花板；\n" +
                            "🔥 耐克Air Max 270 React - 当前折扣力度大，立省400元。\n\n" +
                            "你对哪个品类比较感兴趣？我可以深入推荐。",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 家居/家电
            message.contains("家居") || message.contains("家电") || message.contains("家用") -> {
                val recommendations = products.filter { it.categoryId == "cat_02" }.take(3)

                ChatMessage(
                    content = "家居好物推荐来了：\n\n" +
                            "🏠 德龙咖啡机 - 在家就能喝到咖啡馆级别的拿铁，活动价省1400元；\n" +
                            "🏠 石头G20扫地机 - 扫拖一体全自动，养宠家庭必备；\n" +
                            "🏠 小米空气净化器 - 性价比之王，新房除甲醛好帮手。\n\n" +
                            "需要我详细介绍哪一款？",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 运动相关
            message.contains("运动") || message.contains("健身") || message.contains("瑜伽") -> {
                val recommendations = listOf(
                    products.first { it.id == "p012" },
                    products.first { it.id == "p009" },
                    products.first { it.id == "p004" }
                )

                ChatMessage(
                    content = "运动装备推荐：\n\n" +
                            "🏃 Manduka PRO瑜伽垫 - 专业级品质，终身质保；\n" +
                            "👟 耐克Air Max 270 React - 双重缓震，跑步休闲两相宜；\n" +
                            "⌚ Apple Watch Ultra 2 - 户外运动终极伴侣。\n\n" +
                            "你平时主要做什么运动？我帮你精准推荐。",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 护肤/美妆
            message.contains("护肤") || message.contains("美妆") || message.contains("化妆") || message.contains("皮肤") -> {
                val recommendations = listOf(
                    products.first { it.id == "p011" },
                    products.first { it.id == "p005" },
                    products.first { it.id == "p008" }
                )

                ChatMessage(
                    content = "护肤方面，SK-II神仙水绝对是明星单品：\n\n" +
                            "✨ 超过90%的PITERA精华，改善肤质效果显著；\n" +
                            "✨ 现在活动价¥1190，比平时省了400元；\n" +
                            "✨ 建议先买小样测试是否适合自己的肤质。\n\n" +
                            "你的肤质是偏油还是偏干？有什么特别的护肤需求吗？",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }

            // 默认响应
            else -> {
                val recommendations = listOf(
                    products.first { it.id == "p002" },
                    products.first { it.id == "p006" },
                    products.first { it.id == "p013" }
                )

                ChatMessage(
                    content = "你好！我是你的AI购物助手 🛒\n\n" +
                            "我可以帮你：\n" +
                            "🔍 根据需求推荐合适的商品\n" +
                            "💰 对比不同产品的性价比\n" +
                            "🎁 挑选送礼好物\n" +
                            "📸 拍照识别商品并推荐同款\n\n" +
                            "以下是当前最热门的几款商品，你也可以告诉我具体需求，我来帮你精准推荐！",
                    isUser = false,
                    productRecommendations = recommendations
                )
            }
        }
    }

    // ==================== 图像识别模拟结果 ====================

    fun getRecognitionResult(label: String = ""): RecognitionResult {
        val normalizedLabel = label.lowercase()

        return when {
            normalizedLabel.contains("耳机") || normalizedLabel.contains("headphone") -> {
                RecognitionResult(
                    label = "无线蓝牙耳机",
                    confidence = 0.92f,
                    relatedProducts = products.filter {
                        it.tags.any { tag -> tag.contains("耳机") || tag.contains("降噪") }
                    }
                )
            }
            normalizedLabel.contains("手机") || normalizedLabel.contains("phone") -> {
                RecognitionResult(
                    label = "智能手机",
                    confidence = 0.95f,
                    relatedProducts = products.filter {
                        it.tags.any { tag -> tag.contains("旗舰") || tag.contains("5G") }
                    }
                )
            }
            normalizedLabel.contains("鞋") || normalizedLabel.contains("shoe") || normalizedLabel.contains("sneaker") -> {
                RecognitionResult(
                    label = "运动鞋",
                    confidence = 0.88f,
                    relatedProducts = listOf(products.first { it.id == "p009" })
                )
            }
            normalizedLabel.contains("包") || normalizedLabel.contains("bag") || normalizedLabel.contains("backpack") -> {
                RecognitionResult(
                    label = "双肩背包",
                    confidence = 0.85f,
                    relatedProducts = listOf(products.first { it.id == "p010" })
                )
            }
            normalizedLabel.contains("电脑") || normalizedLabel.contains("laptop") -> {
                RecognitionResult(
                    label = "笔记本电脑",
                    confidence = 0.91f,
                    relatedProducts = listOf(products.first { it.id == "p003" })
                )
            }
            else -> {
                RecognitionResult(
                    label = "商品",
                    confidence = 0.75f,
                    relatedProducts = products.shuffled().take(3)
                )
            }
        }
    }

    // ==================== 辅助方法 ====================

    fun getProductById(id: String): Product? = products.find { it.id == id }

    fun getProductsByCategory(categoryId: String): List<Product> =
        products.filter { it.categoryId == categoryId }

    fun searchProducts(query: String): List<Product> {
        val q = query.lowercase()
        return products.filter { product ->
            product.name.lowercase().contains(q) ||
                    product.brand.lowercase().contains(q) ||
                    product.category.lowercase().contains(q) ||
                    product.tags.any { it.lowercase().contains(q) } ||
                    product.description.lowercase().contains(q)
        }
    }

    fun getHotProducts(limit: Int = 6): List<Product> =
        products.sortedByDescending { it.reviewCount }.take(limit)

    fun getDiscountProducts(): List<Product> =
        products.filter { it.discount != null && it.discount!! > 0 }
            .sortedByDescending { it.discount }
}
