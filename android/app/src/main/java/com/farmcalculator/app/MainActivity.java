package com.farmcalculator.app;

import com.getcapacitor.BridgeActivity;

/**
 * Android 端 Capacitor 容器 Activity。
 *
 * 该类不承载业务计算逻辑，只继承 BridgeActivity 以加载 Vite 构建产物、
 * 初始化 Capacitor bridge，并把系统返回键等原生事件转交给前端应用处理。
 */
public class MainActivity extends BridgeActivity {
}
