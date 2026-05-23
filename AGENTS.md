# Repository Guidelines

## Project Structure & Module Organization

This repository contains a single Android project in `SmartShopAI/`. The app module is `SmartShopAI/app/` and uses package `com.smartshop.ai`.

- `app/src/main/java/com/smartshop/ai/`: Kotlin source code.
- `data/model/`, `data/mock/`: product, user, chat, banner, and mock data.
- `di/`: Hilt modules.
- `ui/`: Compose screens, components, navigation, and theme files.
- `app/src/main/res/`: icons, strings, themes, and network security config.

Unit tests should be added under `app/src/test/`. Instrumented and Compose UI tests should be added under `app/src/androidTest/`.

## Build, Test, and Development Commands

Run commands from `SmartShopAI/`.

- `gradle assembleDebug`: builds a debug APK.
- `gradle test`: runs JVM unit tests.
- `gradle connectedAndroidTest`: runs instrumented tests on a connected emulator or device.
- `gradle lint`: runs Android lint checks.
- `gradle clean`: removes generated build outputs.

Gradle wrapper metadata exists, but `gradlew` and `gradlew.bat` are not tracked. If those scripts are restored, prefer them over a system Gradle install.

## Coding Style & Naming Conventions

Use Kotlin, Java 17 targets, and Gradle Kotlin DSL. Follow standard Kotlin formatting: 4-space indentation and concise expression bodies when readable.

Use `PascalCase` for Compose screens and components, such as `HomeScreen` and `ProductCard`. Use `camelCase` for functions, properties, and locals. Put reusable UI in `ui/components/` and route changes in `ui/navigation/`.

## Testing Guidelines

Use JUnit 4 and MockK for local tests. Use AndroidX test, Espresso, and Compose UI test APIs for instrumented coverage. Name tests after the behavior or screen, for example `ProductRepositoryTest` or `HomeScreenTest`.

Add tests for data logic, navigation behavior, and non-trivial UI state. Run `gradle test` before opening a PR. Run `gradle connectedAndroidTest` when changing Compose interactions, permissions, CameraX, or framework integration.

## Commit & Pull Request Guidelines

The current history is minimal and does not establish a strict convention. Use short, imperative commit subjects such as `Add product search screen` or `Fix camera permission flow`.

Pull requests should include a summary, test results, and screenshots or recordings for UI changes. Link related issues when available. Call out configuration, permission, or API changes explicitly.

## Security & Configuration Tips

Do not commit local secrets, signing keys, API tokens, or machine-specific IDE settings. Keep network policy changes in `app/src/main/res/xml/network_security_config.xml` easy to review, and document new runtime permissions in PRs.
