# Draft mr/hi translations. NEEDS NATIVE-SPEAKER REVIEW before the demo (see README).
# Placeholders like {0}, {day} must stay exactly as they are. Digits stay Latin.
T = {
"— Same as the last price": ("— मागील भावाइतकाच", "— पिछले भाव जितना ही"),
"{0} qtl": ("{0} क्विंटल", "{0} क्विंटल"),
"{observations} days": ("{observations} दिवस", "{observations} दिन"),
"{observations} days of data": ("{observations} दिवसांचा डेटा", "{observations} दिन का डेटा"),
"{r}d": ("{r} दि.", "{r} दि."),
"/quintal": ("/क्विंटल", "/क्विंटल"),
"▲ {abs} ({p}) since the last price": ("▲ मागील भावापेक्षा {abs} ({p}) जास्त", "▲ पिछले भाव से {abs} ({p}) ज़्यादा"),
"▼ {abs} ({p}) since the last price": ("▼ मागील भावापेक्षा {abs} ({p}) कमी", "▼ पिछले भाव से {abs} ({p}) कम"),
"1y": ("1 वर्ष", "1 साल"),
"7 days": ("7 दिवस", "7 दिन"),
"A forecast needs at least {need} days of prices. This mandi has {observations} so far.": (
  "अंदाजासाठी किमान {need} दिवसांचे भाव हवेत. या बाजारात आत्तापर्यंत {observations} दिवसांचे भाव आहेत.",
  "अनुमान के लिए कम से कम {need} दिन के भाव चाहिए। इस मंडी में अभी तक {observations} दिन के भाव हैं।"),
"A machine-learning model trained on prices, arrivals, weather and market signals across mandis.": (
  "अनेक बाजारांतील भाव, आवक, हवामान आणि बाजारातील घडामोडींवर प्रशिक्षित मशीन-लर्निंग मॉडेल.",
  "कई मंडियों के भाव, आवक, मौसम और बाज़ार संकेतों पर प्रशिक्षित मशीन-लर्निंग मॉडल।"),
"A mandi needs {0} days of prices before we forecast, and {1} days before accuracy can be tested.": (
  "अंदाज देण्यापूर्वी बाजाराचे {0} दिवसांचे भाव लागतात, आणि अचूकता तपासण्यासाठी {1} दिवसांचे.",
  "अनुमान देने से पहले मंडी के {0} दिन के भाव चाहिए, और सटीकता जाँचने के लिए {1} दिन के।"),
"A mix of the recent average and the recent trend. Used automatically when there is enough history but no advanced model has been approved.": (
  "अलीकडील सरासरी आणि अलीकडील कल यांचे मिश्रण. पुरेसा इतिहास असेल पण कोणतेही प्रगत मॉडेल मंजूर झाले नसेल तेव्हा आपोआप वापरले जाते.",
  "हाल के औसत और हाल के रुझान का मिश्रण। पर्याप्त इतिहास होने पर, जब कोई उन्नत मॉडल स्वीकृत न हो, अपने आप इस्तेमाल होता है।"),
"A more complex model is used only if it beats a simple one on real past prices. Every forecast names the model that made it.": (
  "प्रत्यक्ष जुन्या भावांवर साध्या मॉडेलपेक्षा चांगले ठरले तरच गुंतागुंतीचे मॉडेल वापरले जाते. प्रत्येक अंदाजासोबत तो कोणत्या मॉडेलने दिला ते दाखवले जाते.",
  "असली पुराने भावों पर सरल मॉडल से बेहतर साबित होने पर ही जटिल मॉडल इस्तेमाल होता है। हर अनुमान के साथ उसे बनाने वाले मॉडल का नाम दिखाया जाता है।"),
"A regression on recent prices, mandi arrivals, rainfall and district prices. Signals that did not change recently are dropped automatically.": (
  "अलीकडील भाव, बाजारातील आवक, पाऊस आणि जिल्ह्यातील भाव यांवर आधारित रिग्रेशन. अलीकडे न बदललेले घटक आपोआप वगळले जातात.",
  "हाल के भाव, मंडी आवक, बारिश और ज़िले के भावों पर आधारित रिग्रेशन। हाल में न बदले संकेत अपने आप हटा दिए जाते हैं।"),
"About forecasts": ("अंदाजाविषयी", "अनुमान के बारे में"),
"Accuracy: not measured yet. We are collecting history first.": ("अचूकता: अजून मोजलेली नाही. आधी भावांचा इतिहास गोळा करत आहोत.", "सटीकता: अभी मापी नहीं गई। पहले भावों का इतिहास जुटा रहे हैं।"),
"Advice": ("सल्ला", "सलाह"),
"Alerts": ("सूचना", "अलर्ट"),
"Alerts arrive by SMS, not in this app. Signing in is needed to set them up. This screen is coming next.": (
  "सूचना SMS ने येतात, या ॲपमध्ये नाही. त्या लावण्यासाठी लॉगिन आवश्यक आहे. ही सुविधा लवकरच येत आहे.",
  "अलर्ट SMS से आते हैं, इस ऐप में नहीं। इन्हें लगाने के लिए लॉगिन ज़रूरी है। यह सुविधा जल्द आ रही है।"),
"arrivals": ("आवक", "आवक"),
"Arrivals": ("आवक", "आवक"),
"Available": ("उपलब्ध", "उपलब्ध"),
"Average % error": ("सरासरी % चूक", "औसत % त्रुटि"),
"Average + trend": ("सरासरी + कल", "औसत + रुझान"),
"Average of recent prices, carried forward.": ("अलीकडील भावांची सरासरी, पुढे चालवलेली.", "हाल के भावों का औसत, आगे बढ़ाया गया।"),
"Average of the last 7 days of prices, carried forward. Used when a mandi has only 10–14 days of history.": (
  "मागील 7 दिवसांच्या भावांची सरासरी, पुढे चालवलेली. बाजाराचा फक्त 10–14 दिवसांचा इतिहास असताना वापरली जाते.",
  "पिछले 7 दिनों के भावों का औसत, आगे बढ़ाया गया। जब मंडी का केवल 10–14 दिन का इतिहास हो, तब इस्तेमाल होता है।"),
"Bars below: how much produce arrived at the mandi. More arrivals often mean lower prices.": (
  "खालील पट्ट्या: बाजारात किती माल आला. आवक जास्त असल्यास भाव अनेकदा कमी होतो.",
  "नीचे की पट्टियाँ: मंडी में कितना माल आया। ज़्यादा आवक पर भाव अक्सर गिरता है।"),
"Bars: arrivals at the mandi (quintal)": ("पट्ट्या: बाजारातील आवक (क्विंटल)", "पट्टियाँ: मंडी में आवक (क्विंटल)"),
"Better price nearby": ("जवळ चांगला भाव", "पास में बेहतर भाव"),
"Change": ("बदल", "बदलाव"),
"Choose your language": ("तुमची भाषा निवडा", "अपनी भाषा चुनें"),
"Close": ("बंद करा", "बंद करें"),
"Confidence": ("विश्वास", "भरोसा"),
"Continues the recent price trend in a straight line.": ("अलीकडील भावांचा कल सरळ रेषेत पुढे नेतो.", "हाल के भाव के रुझान को सीधी रेखा में आगे बढ़ाता है।"),
"Crop": ("पीक", "फसल"),
"Dashed line: the model’s forecast for the next few days.": ("तुटक रेषा: पुढील काही दिवसांचा मॉडेलचा अंदाज.", "टूटी रेखा: अगले कुछ दिनों का मॉडल का अनुमान।"),
"Enlarge the forecast ›": ("अंदाज मोठा करून पहा ›", "अनुमान बड़ा करके देखें ›"),
"Falling": ("घसरता", "गिरता"),
"Finding your location…": ("तुमचे ठिकाण शोधत आहोत…", "आपकी जगह ढूँढ रहे हैं…"),
"forecast": ("अंदाज", "अनुमान"),
"Forecast": ("अंदाज", "अनुमान"),
"Forecast accuracy": ("अंदाजाची अचूकता", "अनुमान की सटीकता"),
"forecast updated {0}": ("अंदाज {0} ला अद्ययावत", "अनुमान {0} बजे अपडेट"),
"Generated": ("तयार केला", "बनाया गया"),
"Get an SMS when the price at your mandi goes above or below a price you choose.": (
  "तुमच्या बाजारातील भाव तुम्ही ठरवलेल्या भावाच्या वर किंवा खाली गेल्यावर SMS मिळवा.",
  "आपकी मंडी का भाव आपके चुने भाव से ऊपर या नीचे जाने पर SMS पाएँ।"),
"Gradient boosting (GBM)": ("ग्रेडियंट बूस्टिंग (GBM)", "ग्रेडिएंट बूस्टिंग (GBM)"),
"High": ("जास्त", "ज़्यादा"),
"high confidence": ("जास्त विश्वास", "ज़्यादा भरोसा"),
"Holt-Winters smoothing: follows the level and trend of prices over time.": ("होल्ट-विंटर्स पद्धत: वेळेनुसार भावांची पातळी आणि कल यांचा मागोवा घेते.", "होल्ट-विंटर्स पद्धति: समय के साथ भाव के स्तर और रुझान को पकड़ती है।"),
"How forecasts are checked": ("अंदाज कसे तपासले जातात", "अनुमान कैसे जाँचे जाते हैं"),
"How forecasts work": ("अंदाज कसे काढले जातात", "अनुमान कैसे बनते हैं"),
"In past tests, the real price stayed inside the likely range {inTen} times out of 10.": (
  "जुन्या चाचण्यांमध्ये प्रत्यक्ष भाव 10 पैकी {inTen} वेळा संभाव्य पट्ट्यात राहिला.",
  "पुराने परीक्षणों में असली भाव 10 में से {inTen} बार संभावित दायरे में रहा।"),
"In past tests, the real price stayed inside this range {inTen} times out of 10.": (
  "जुन्या चाचण्यांमध्ये प्रत्यक्ष भाव 10 पैकी {inTen} वेळा या पट्ट्यात राहिला.",
  "पुराने परीक्षणों में असली भाव 10 में से {inTen} बार इस दायरे में रहा।"),
"Krishi Bazaar": ("कृषी बाजार", "कृषि बाज़ार"),
"Language": ("भाषा", "भाषा"),
"Latest mandi price (modal)": ("बाजारातील ताजा भाव (सर्वसाधारण)", "मंडी का ताज़ा भाव (मॉडल)"),
"likely": ("संभाव्य", "संभावित"),
"Likely range for the next {horizonDays} days: {lo}–{hi} (model’s estimate).": (
  "पुढील {horizonDays} दिवसांचा संभाव्य भाव: {lo}–{hi} (मॉडेलचा अंदाज).",
  "अगले {horizonDays} दिनों का संभावित भाव: {lo}–{hi} (मॉडल का अनुमान)।"),
"Live": ("चालू", "चालू"),
"Low": ("कमी", "कम"),
"low confidence": ("कमी विश्वास", "कम भरोसा"),
"Mandi": ("बाजार", "मंडी"),
"Mandi price of {day}": ("{day} चा बाजारभाव", "{day} का मंडी भाव"),
"Mandi prices · {district}": ("बाजारभाव · {district}", "मंडी भाव · {district}"),
"max": ("कमाल", "अधिकतम"),
"medium confidence": ("मध्यम विश्वास", "मध्यम भरोसा"),
"min": ("किमान", "न्यूनतम"),
"Min {0} · Max {1}": ("किमान {0} · कमाल {1}", "न्यूनतम {0} · अधिकतम {1}"),
"Model details are not available.": ("मॉडेलची माहिती उपलब्ध नाही.", "मॉडल की जानकारी उपलब्ध नहीं है।"),
"Model version": ("मॉडेल आवृत्ती", "मॉडल संस्करण"),
"Model: {label}": ("मॉडेल: {label}", "मॉडल: {label}"),
"Models we use": ("आम्ही वापरतो ती मॉडेल्स", "हमारे इस्तेमाल किए मॉडल"),
"Moving average": ("चल सरासरी", "चल औसत"),
"next {0} days": ("पुढील {0} दिवस", "अगले {0} दिन"),
"No advice for today": ("आजसाठी सल्ला नाही", "आज के लिए सलाह नहीं"),
"No forecast": ("अंदाज नाही", "अनुमान नहीं"),
"No mandi price for the last {0} days (dotted line).": ("मागील {0} दिवस बाजारभाव नाही (ठिपक्यांची रेषा).", "पिछले {0} दिन मंडी भाव नहीं (बिंदुओं वाली रेखा)।"),
"No other mandi reported this crop in the last 7 days.": ("मागील 7 दिवसांत इतर कोणत्याही बाजारात या पिकाचा भाव नोंदला नाही.", "पिछले 7 दिनों में किसी और मंडी में इस फसल का भाव दर्ज नहीं हुआ।"),
"No recent price for this crop at this mandi.": ("या बाजारात या पिकाचा अलीकडील भाव नाही.", "इस मंडी में इस फसल का हाल का भाव नहीं है।"),
"None nearby": ("जवळ नाही", "पास में नहीं"),
"Normal": ("सामान्य", "सामान्य"),
"Not enough data for a forecast yet": ("अंदाजासाठी अजून पुरेसा डेटा नाही", "अनुमान के लिए अभी पर्याप्त डेटा नहीं"),
"Not enough price history to make an honest forecast.": ("प्रामाणिक अंदाजासाठी पुरेसा भावांचा इतिहास नाही.", "ईमानदार अनुमान के लिए पर्याप्त भाव इतिहास नहीं है।"),
"Not measured yet": ("अजून मोजलेली नाही", "अभी मापी नहीं गई"),
"Not published yet": ("अजून प्रकाशित नाही", "अभी प्रकाशित नहीं"),
"not reported": ("नोंद नाही", "दर्ज नहीं"),
"Offline": ("ऑफलाइन", "ऑफ़लाइन"),
"Other mandis · {0}": ("इतर बाजार · {0}", "अन्य मंडियाँ · {0}"),
"Price": ("भाव", "भाव"),
"Price alerts": ("भाव सूचना", "भाव अलर्ट"),
"Price chart with forecast": ("अंदाजासह भावाचा आलेख", "अनुमान सहित भाव का चार्ट"),
"Price fell {pct} in {days} days.": ("{days} दिवसांत भाव {pct} ने घटला.", "{days} दिनों में भाव {pct} गिरा।"),
"Price from {day} ({age} days old)": ("{day} चा भाव ({age} दिवस जुना)", "{day} का भाव ({age} दिन पुराना)"),
"Price history used": ("वापरलेला भावांचा इतिहास", "इस्तेमाल भाव इतिहास"),
"Price of {0}": ("{0} चा भाव", "{0} का भाव"),
"Price rose {pct} in {days} days.": ("{days} दिवसांत भाव {pct} ने वाढला.", "{days} दिनों में भाव {pct} बढ़ा।"),
"Price trend": ("भावाचा कल", "भाव का रुझान"),
"Price was steady over {days} days.": ("{days} दिवसांत भाव स्थिर राहिला.", "{days} दिनों में भाव स्थिर रहा।"),
"Prices": ("बाजारभाव", "मंडी भाव"),
"Prices in ₹ per quintal. Change is against the previous reported day.": ("भाव ₹ प्रति क्विंटल. बदल मागील नोंदवलेल्या दिवसाच्या तुलनेत.", "भाव ₹ प्रति क्विंटल। बदलाव पिछले दर्ज दिन की तुलना में।"),
"Provisional: tested on a few mandis only.": ("तात्पुरते: फक्त काही बाजारांवर तपासलेले.", "अस्थायी: केवल कुछ मंडियों पर जाँचा गया।"),
"qtl": ("क्विं.", "क्विं."),
"Range": ("कालावधी", "अवधि"),
"Rising": ("वाढता", "बढ़ता"),
"Seasonal smoothing": ("हंगामी सरासरी पद्धत", "मौसमी स्मूदिंग"),
"Sell / Hold / Wait is decided by the server from mandi arrivals, nearby storage and the forecast. The app shows the advice exactly as the server gives it.": (
  "विका / थांबा हा सल्ला सर्व्हर बाजारातील आवक, जवळची साठवण आणि अंदाज यांवरून ठरवतो. ॲप तो सल्ला जसाच्या तसा दाखवते.",
  "बेचें / रुकें की सलाह सर्वर मंडी आवक, पास के भंडारण और अनुमान से तय करता है। ऐप वह सलाह जैसी की तैसी दिखाता है।"),
"Send me an SMS when the price changes": ("भाव बदलल्यावर मला SMS पाठवा", "भाव बदलने पर मुझे SMS भेजें"),
"Shaded area: the likely range. The real price can still fall outside it.": ("छटा असलेला भाग: संभाव्य भाव. प्रत्यक्ष भाव याच्या बाहेरही जाऊ शकतो.", "छायांकित भाग: संभावित दायरा। असली भाव इसके बाहर भी जा सकता है।"),
"Show this on my Today screen": ("हे माझ्या 'आज' स्क्रीनवर दाखवा", "इसे मेरी 'आज' स्क्रीन पर दिखाएँ"),
"Solid line: real mandi prices (modal price, ₹ per quintal).": ("सलग रेषा: प्रत्यक्ष बाजारभाव (सर्वसाधारण भाव, ₹ प्रति क्विंटल).", "ठोस रेखा: असली मंडी भाव (मॉडल भाव, ₹ प्रति क्विंटल)।"),
"Sort by distance from me": ("माझ्यापासूनच्या अंतरानुसार लावा", "मुझसे दूरी के हिसाब से लगाएँ"),
"Steady": ("स्थिर", "स्थिर"),
"Step {0} of 3": ("पायरी {0} / 3", "चरण {0} / 3"),
"Storage": ("साठवण", "भंडारण"),
"Straight-line trend": ("सरळ रेषेतील कल", "सीधी रेखा का रुझान"),
"The forecast is out of date, so it is hidden. Waiting for new mandi data.": ("अंदाज जुना आहे, म्हणून लपवला आहे. नवीन बाजार डेटाची वाट पाहत आहोत.", "अनुमान पुराना है, इसलिए छिपाया गया है। नए मंडी डेटा का इंतज़ार है।"),
"There is not enough price history yet for an honest forecast.": ("प्रामाणिक अंदाजासाठी अजून पुरेसा भावांचा इतिहास नाही.", "ईमानदार अनुमान के लिए अभी पर्याप्त भाव इतिहास नहीं है।"),
"This forecast is more than a day old. New prices have not arrived from the mandi yet.": ("हा अंदाज एक दिवसापेक्षा जुना आहे. बाजारातून नवीन भाव अजून आलेले नाहीत.", "यह अनुमान एक दिन से पुराना है। मंडी से नए भाव अभी नहीं आए हैं।"),
"This mandi has not reported a price for this crop in the last 15 days. Try a nearby mandi below.": ("या बाजाराने मागील 15 दिवसांत या पिकाचा भाव नोंदवलेला नाही. खालील जवळचा बाजार पहा.", "इस मंडी ने पिछले 15 दिनों में इस फसल का भाव दर्ज नहीं किया। नीचे पास की मंडी देखें।"),
"today": ("आज", "आज"),
"Today": ("आज", "आज"),
"Tomorrow likely {0}": ("उद्या संभाव्य {0}", "कल संभावित {0}"),
"Trend with arrivals and weather": ("आवक व हवामानासह कल", "आवक और मौसम सहित रुझान"),
"Typical error": ("सर्वसाधारण चूक", "सामान्य त्रुटि"),
"Until then, every forecast is shown with its likely range and the name of the model that made it, never as a single certain number.": (
  "तोपर्यंत प्रत्येक अंदाज त्याच्या संभाव्य पट्ट्यासह आणि तो देणाऱ्या मॉडेलच्या नावासह दाखवला जातो, कधीही एकच निश्चित आकडा म्हणून नाही.",
  "तब तक हर अनुमान उसके संभावित दायरे और उसे बनाने वाले मॉडल के नाम के साथ दिखाया जाता है, कभी एक पक्के आँकड़े के रूप में नहीं।"),
"Updating…": ("अद्ययावत करत आहे…", "अपडेट हो रहा है…"),
"Verified history": ("तपासलेला इतिहास", "जाँचा गया इतिहास"),
"We are still collecting mandi history. Accuracy will be published only after the forecasts have been tested against real past prices.": (
  "आम्ही अजून बाजारभावांचा इतिहास गोळा करत आहोत. प्रत्यक्ष जुन्या भावांवर अंदाज तपासल्यानंतरच अचूकता प्रकाशित केली जाईल.",
  "हम अभी मंडी भावों का इतिहास जुटा रहे हैं। असली पुराने भावों पर अनुमान जाँचने के बाद ही सटीकता प्रकाशित की जाएगी।"),
"What the chart shows": ("आलेख काय दाखवतो", "चार्ट क्या दिखाता है"),
"Where the advice comes from": ("सल्ला कुठून येतो", "सलाह कहाँ से आती है"),
"Which crop do you sell?": ("तुम्ही कोणते पीक विकता?", "आप कौन सी फसल बेचते हैं?"),
"Which mandi do you sell at?": ("तुम्ही कोणत्या बाजारात विकता?", "आप किस मंडी में बेचते हैं?"),
"Which model made this forecast?": ("हा अंदाज कोणत्या मॉडेलने दिला?", "यह अनुमान किस मॉडल ने बनाया?"),
"You are offline. Showing the prices saved on this phone. Check the date on each price.": (
  "तुम्ही ऑफलाइन आहात. या फोनवर साठवलेले भाव दाखवत आहोत. प्रत्येक भावाची तारीख तपासा.",
  "आप ऑफ़लाइन हैं। इस फ़ोन में सहेजे भाव दिखा रहे हैं। हर भाव की तारीख़ जाँचें।"),
}

if __name__ == "__main__":
    import re, sys
    for idx, lang in ((0, "mr"), (1, "hi")):
        p = f"src/i18n/locales/{lang}/messages.po"
        s = open(p, encoding="utf-8").read()
        missing = []
        def fill(m):
            mid = m.group(1)
            key = mid.encode().decode('unicode_escape').encode('latin-1').decode('utf-8') if '\\' in mid else mid
            if key in T:
                val = T[key][idx].replace('"', '\\"')
                return f'msgid "{mid}"\nmsgstr "{val}"'
            missing.append(mid)
            return m.group(0)
        s = re.sub(r'msgid "(.+)"\nmsgstr ""', fill, s)
        open(p, "w", encoding="utf-8").write(s)
        print(lang, "missing:", missing)
        # placeholder check
        for k, v in T.items():
            ph = sorted(re.findall(r"\{\w+\}", k))
            if sorted(re.findall(r"\{\w+\}", v[idx])) != ph:
                print("PLACEHOLDER MISMATCH", lang, k); sys.exit(1)
