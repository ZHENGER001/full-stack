# Repository Guidelines

## Project Structure & Module Organization

This repository is a single Android project with one application module, `app`, using package `com.smartshop.ai`.

- `app/src/main/java/com/smartshop/ai/`: Kotlin source code.
- `data/model/` and `data/mock/`: product, user, chat, banner, and mock data types.
- `di/`: Hilt dependency injection modules.
- `ui/`: Jetpack Compose screens, components, navigation, and theme code.
- `app/src/main/res/`: launcher icons, strings, themes, and XML configuration such as `network_security_config.xml`.

Add JVM unit tests under `app/src/test/`. Add instrumented and Compose UI tests under `app/src/androidTest/`.

## Build, Test, and Development Commands

Run commands from the repository root.

- `gradle assembleDebug`: builds the debug APK.
- `gradle installDebug`: installs the debug APK on a connected emulator or device.
- `gradle test`: runs local JVM unit tests.
- `gradle connectedAndroidTest`: runs instrumented tests on a connected Android device.
- `gradle lint`: runs Android lint checks.
- `gradle clean`: removes generated build outputs.

Gradle wrapper metadata is present, but `gradlew` and `gradlew.bat` are not tracked. If wrapper scripts are restored, prefer `./gradlew` or `gradlew.bat` over a system Gradle install.

## Coding Style & Naming Conventions

Use Kotlin, Java 17 targets, Gradle Kotlin DSL, Hilt, and Jetpack Compose. Follow standard Kotlin formatting with 4-space indentation. Prefer concise expression bodies when they remain readable.

Use `PascalCase` for Compose screens and components, for example `HomeScreen` or `ProductCard`. Use `camelCase` for functions, properties, and local variables. Place reusable UI in `ui/components/` and navigation changes in `ui/navigation/`.

## Testing Guidelines

Use JUnit 4 and MockK for local tests. Use AndroidX Test, Espresso, and Compose UI test APIs for instrumented coverage. Name test files after the behavior or screen, such as `ProductRepositoryTest` or `HomeScreenTest`.

Add tests for data logic, navigation behavior, and non-trivial UI state. Run `gradle test` before opening a pull request. Run `gradle connectedAndroidTest` when changing Compose interactions, permissions, CameraX, or Android framework integration.

## Commit & Pull Request Guidelines

The current history is minimal, so use short imperative commit subjects such as `Add product search screen` or `Fix camera permission flow`.

Pull requests should include a summary, test results, and screenshots or recordings for UI changes. Link related issues when available. Call out configuration, permission, API, or network policy changes explicitly.

## Security & Configuration Tips

Do not commit local secrets, signing keys, API tokens, or machine-specific IDE settings. Keep `local.properties` local. Make changes to `app/src/main/res/xml/network_security_config.xml` easy to review and document new runtime permissions in PRs.
