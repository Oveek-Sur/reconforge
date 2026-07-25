/*
 * ReconForge — Universal Android SSL Pinning + TrustManager bypass
 * Makes the target app accept ANY server certificate (incl. mitmproxy's CA),
 * so an intercepting proxy can decrypt its HTTPS traffic.
 *
 * Covers: Conscrypt TrustManagerImpl (Android 7+), SSLContext custom TrustManagers,
 * OkHttp3 CertificatePinner, HostnameVerifier, X509TrustManagerExtensions,
 * TrustKit, Appcelerator, and the RN/OkHttp networking stack.
 *
 * Usage: frida -U -f <pkg> -l frida-ssl-unpin.js   (or via frida_spawn.py)
 */
setTimeout(function () {
  Java.perform(function () {
    console.log('[*] ReconForge SSL unpinning loaded');

    var UNVERIFIED_HOSTS = [];

    // ---- 1. Conscrypt TrustManagerImpl (the one that rejected mitmproxy) ----
    try {
      var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
      var ArrayList = Java.use('java.util.ArrayList');
      // Android 7-13: checkTrustedRecursive returns List<X509Certificate>
      TMI.checkTrustedRecursive.implementation = function (a1, a2, a3, a4, a5, a6) {
        console.log('[+] TrustManagerImpl.checkTrustedRecursive bypassed');
        return ArrayList.$new();
      };
      // Newer path: verifyChain returns the chain untouched
      try {
        TMI.verifyChain.implementation = function (untrusted, anchors, host, clientAuth, ocsp, tlsSct) {
          console.log('[+] TrustManagerImpl.verifyChain bypassed: ' + host);
          return untrusted;
        };
      } catch (e) {}
      console.log('[+] Hooked Conscrypt TrustManagerImpl');
    } catch (e) { console.log('[-] TrustManagerImpl: ' + e); }

    // ---- 2. SSLContext.init — swap in an all-trusting TrustManager ----
    try {
      var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
      var SSLContext = Java.use('javax.net.ssl.SSLContext');
      var TrustManager = Java.registerClass({
        name: 'com.reconforge.TrustAll',
        implements: [X509TrustManager],
        methods: {
          checkClientTrusted: function (chain, authType) {},
          checkServerTrusted: function (chain, authType) {},
          getAcceptedIssuers: function () { return []; }
        }
      });
      var TrustManagers = [TrustManager.$new()];
      var SSLContext_init = SSLContext.init.overload(
        '[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom');
      SSLContext_init.implementation = function (km, tm, sr) {
        console.log('[+] SSLContext.init hooked -> all-trusting TrustManager');
        SSLContext_init.call(this, km, TrustManagers, sr);
      };
      console.log('[+] Hooked SSLContext.init');
    } catch (e) { console.log('[-] SSLContext: ' + e); }

    // ---- 3. OkHttp3 CertificatePinner (RN networking + FastFetch use OkHttp) ----
    try {
      var CertificatePinner = Java.use('okhttp3.CertificatePinner');
      var overloads = CertificatePinner.check.overloads;
      overloads.forEach(function (ov) {
        ov.implementation = function () {
          console.log('[+] OkHttp3 CertificatePinner.check bypassed: ' + arguments[0]);
          return;
        };
      });
      console.log('[+] Hooked OkHttp3 CertificatePinner (' + overloads.length + ' overloads)');
    } catch (e) { console.log('[-] OkHttp CertificatePinner: ' + e); }

    // ---- 4. HostnameVerifier — accept all hostnames ----
    try {
      var HttpsURLConnection = Java.use('javax.net.ssl.HttpsURLConnection');
      HttpsURLConnection.setDefaultHostnameVerifier.implementation = function (v) {
        console.log('[+] setDefaultHostnameVerifier bypassed');
        return;
      };
      HttpsURLConnection.setSSLSocketFactory.implementation = function (f) {
        console.log('[+] setSSLSocketFactory bypassed');
        return;
      };
      HttpsURLConnection.setHostnameVerifier.implementation = function (v) {
        console.log('[+] setHostnameVerifier bypassed');
        return;
      };
    } catch (e) { console.log('[-] HttpsURLConnection: ' + e); }

    // ---- 5. X509TrustManagerExtensions (used by some pinning libs) ----
    try {
      var X509Ext = Java.use('android.net.http.X509TrustManagerExtensions');
      X509Ext.checkServerTrusted.implementation = function (chain, authType, host) {
        console.log('[+] X509TrustManagerExtensions.checkServerTrusted bypassed: ' + host);
        return Java.use('java.util.ArrayList').$new();
      };
    } catch (e) {}

    // ---- 6. TrustKit ----
    try {
      var TrustKit = Java.use('com.datatheorem.android.trustkit.pinning.OkHostnameVerifier');
      TrustKit.verify.overload('java.lang.String', 'javax.net.ssl.SSLSession').implementation = function (h, s) {
        console.log('[+] TrustKit OkHostnameVerifier bypassed: ' + h);
        return true;
      };
    } catch (e) {}

    // ---- 7. Appcelerator PinningTrustManager ----
    try {
      var Appc = Java.use('appcelerator.https.PinningTrustManager');
      Appc.checkServerTrusted.implementation = function () {
        console.log('[+] Appcelerator PinningTrustManager bypassed');
      };
    } catch (e) {}

    console.log('[*] ReconForge SSL unpinning active');
  });
}, 0);
