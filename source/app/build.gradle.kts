plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val testAbi = providers.gradleProperty("testAbi").getOrElse("phone")
require(testAbi in listOf("phone", "arm32", "x86_64"))
android {
    namespace = "org.esurfing.hunan"
    compileSdk = 35
    ndkVersion = "28.0.13004108"
    defaultConfig {
        applicationId = "org.esurfing.hunan"
        minSdk = 26
        targetSdk = 35
        versionCode = 36
        versionName = "0.2.24-background"
        externalNativeBuild { cmake { arguments += "-DANDROID_STL=none" } }
    }
    externalNativeBuild { cmake { path = file("src/main/cpp/CMakeLists.txt"); version = "3.22.1"; buildStagingDirectory = file("../../cxx") } }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes {
        debug { signingConfig = null; ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") } }
        release { isMinifyEnabled = false; ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") } }
        create("candidate") {
            initWith(getByName("debug"))
        }
        create("isolation") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".isolation"
            versionNameSuffix = "-isolation"
            ndk { abiFilters.clear(); abiFilters += when(testAbi) { "arm32" -> listOf("armeabi-v7a"); "x86_64" -> listOf("x86_64"); else -> listOf("arm64-v8a", "armeabi-v7a") } }
            externalNativeBuild { cmake { arguments += "-DHUNAN_ISOLATION=ON" } }
        }
    }
}
dependencies { implementation(files("libs/okhttp-4.12.0.jar", "libs/okio-jvm-3.6.0.jar")) }
