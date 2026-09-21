////////////////////////////////////////////////////////////////////////////////
// LabCI HKEX Widget - Equity
//////////////////////////////////////////////////////////////////////////////////

(function($) {

//################################################################################
//################################################################################
// The LabCI object for Generic Widget Package
// LabCI = { WP: { ... } }

if (typeof(LabCI)==="undefined") LabCI = { WP: { } };
else if (typeof(LabCI.WP)==="undefined") LabCI.WP = { };

//################################################################################

// Create a new EquityPageObj ...
LabCI.WP.createequitypageobj = function() {
    var pobj = LabCI.AbstractPageObj.extend("lhkexw-equity", LabCI.WP.EquityPageObj);
    return pobj;
};

// The EquityPageObj class
// The main object definition is here...
LabCI.WP.EquityPageObj = {

    ////////////////////////////////////////////////////////////////////
    // Some setting constants
    ////////////////////////////////////////////////////////////////////
    $section_table: null,
    $overflowrow: null,

    $optionsrow: null,
    $opt: null,
    $collist: null,
    $loadrow: null,
    $scroll_tabs: null,
    $hsirow: null,

    curdata: null,
    curindexric: null,
    curchartintopt: null,

    chartric: null,
    chartpClose: null,
    force_ddMMM: false,
    force_MMMyy: false,

    product : null,
    sc_lang: 'en',

    ddMMMformat: '%d %b',
    MMMyyformat: '%b %y',
    
    initImpl: function() {
        // Get ready
        var that = this;
        if (this.lang !== 'en'){
            this.ddMMMformat = '%b%d日';
            this.MMMyyformat = '%y年%b';
        }
        if (LabCI.getLang() === 'zh_HK')
            this.sc_lang = 'zh-hk';
        else if (LabCI.getLang() === 'chn')
            this.sc_lang = 'zh-cn';

        ////////////////////////////////////////////////////////////////////
        //testframe get parameter
//        this.product = LabCI.getProductEquity("product");
        if (LabCI.getProductEquity)
            this.product = LabCI.getProductEquity("product");
        else
            this.product = LabCI.Utils.getURLParameter("product");

        // Create the HTML...
        this.$section_table = this.$pageobj.find(".section_table");
        this.$equity_future = this.$pageobj.find(".equity_future");
        this.$equity_option = this.$pageobj.find(".equity_option");
        this.$sec_max = this.$pageobj.find(".sec_max");
        this.$overflowrow = this.$pageobj.find(".overflowrow");
        this.$loadrow = this.$pageobj.find(".loadrow");

        this.$optionsrow = this.$pageobj.find(".optionsrow");
        this.$opt = this.$pageobj.find(".opt");
        this.$collist = this.$pageobj.find(".collist");
        this.$hsirow = this.$pageobj.find(".hsirow");
        this.$scroll_tabs = this.$pageobj.find(".hkex_scroll_tabs");
        
        //product spec        
        that.$section_table.find(".ps").on('click',function(){
            var product=LabCI.Utils.getURLParameter("product");
            
            if (product ==='HGT')
		window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Hang-Seng-Gross-Total-Return-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'HNT')
		window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Hang-Seng-Net-Total-Return-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === "HSN" || product === "HST")
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Hang-Seng-Total-Return-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'HHT')
		window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-China-Enterprises-Index/Hang-Seng-China-Enterprises-Gross-Total-Return-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'HHN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-China-Enterprises-Index/Hang-Seng-China-Enterprises-Net-Total-Return-Index-Futures?sc_lang=' + that.sc_lang;            
            else if (product === 'MXJ')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Asia-ex-Japan-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'HSI')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Hang-Seng-Index-Futures?product=HSI&sc_lang=' + that.sc_lang;
            else if (product === 'HBI')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Biotech-Index/Hang-Seng-Biotech-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'MHI')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Mini-Hang-Seng-Index-Futures?product=MHI&sc_lang=' + that.sc_lang;
            else if (product === 'XHS')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Hang-Seng-Index-Options?&product=XHS&sc_lang=' + that.sc_lang;
            else if (product === 'HHI' || product === 'XHH')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-China-Enterprises-Index/Hang-Seng-China-Enterprises-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'MCH')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-China-Enterprises-Index/Mini-H-shares-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'CHH')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/CES-China-120-Index/CES-China-120-Index-Futures?product=CHH&sc_lang=' + that.sc_lang;
            else if (product === 'DHS')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Dividend-Futures?product=DHS?sc_lang=' + that.sc_lang;
            else if (product === 'DHH')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Dividend-Futures?product=DHH&sc_lang=' + that.sc_lang;
            else if (product === 'VHS')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/HSI-Volatility-Index-Futures?product=VHS&sc_lang=' + that.sc_lang;
            else if (product === 'GTI' || product === 'MOI' || product === 'MBI' || product === 'MCI' || product === 'MPI' || product === 'ITI' || product === 'SSI')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Sector-Index/Sector-Index-Futures?sc_lang=' + that.sc_lang;
            else if (product === 'EAN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-Asia-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=EAN';
            else if (product === 'MAN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Australia-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MAN';
            else if (product === 'MCN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-China-Free-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MCN';
            else if (product === 'MDN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Indonesia-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MDN';
            else if (product === 'MIN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-India-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MIN';
            else if (product === 'MJU')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Japan-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MJU';
            else if (product === 'MMN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Malaysia-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MMN';
            else if (product === 'MTN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Thailand-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MTN';
            else if (product === 'MTW')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Taiwan-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MTW';
            else if (product === 'MWN')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Taiwan-NTR-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MWN';

            else if (product === 'MSN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Singapore-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MSN';
            else if (product === 'MVN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Vietnam-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MVN';
            else if (product === 'MHN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Hong-Kong-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MHN';
            else if (product === 'MHK') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Hong-Kong-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MHK';
            else if (product === 'MPN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Philippines-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MPN';
            else if (product === 'MID') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Indonesia-Index-(USD)-Futures?sc_lang=' + that.sc_lang + '#&product=MID';
            else if (product === 'MIA') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Indonesia-Index-(USD)-Futures?sc_lang=' + that.sc_lang + '#&product=MIA';
            else if (product === 'EMN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Emerging-Markets-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=EMN';
            else if (product === 'MEM') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Emerging-Markets-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MEM';
            else if (product === 'MEI') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Emerging-Markets-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MEI';
            
            else if (product === 'MDA') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-India-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MDA';
            else if (product === 'MDI') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/APAC-Emerging-Market-Single-Country/Price-Return/MSCI-India-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MDI';
            else if (product === 'MND') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/APAC-Emerging-Market-Single-Country/Price-Return/MSCI-India-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MND';
            else if (product === 'MCU') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-China-Free-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MCU';
            else if (product === 'MCF') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-China-Free-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MCF';
            else if (product === 'MTH') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Thailand-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MTH';
            else if (product === 'MTD') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Thailand-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MTD';
            else if (product === 'MMY') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Malaysia-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MMY';
            else if (product === 'MMA') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Malaysia-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MMA';
            else if (product === 'MPH') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Philippines-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MPH';
            else if (product === 'MPS') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Philippines-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MPS';
            else if (product === 'MVT') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Vietnam-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MVT';
            else if (product === 'MVI') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Vietnam-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MVI';
            else if (product === 'MGN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Singapore-Free-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MGN';
            else if (product === 'MNZ') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-New-Zealand-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MNZ';
            else if (product === 'MXC') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-ex-China-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MXC';
            else if (product === 'MXK') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-ex-Korea-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MXK';
            else if (product === 'MAC') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-Asia-ex-China-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MAC';
            else if (product === 'MAK') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-Asia-ex-Korea-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MAK';
            else if (product === 'MEE') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-EMEA-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MEE';
            else if (product === 'MEL') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-EM-LatAm-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MEL';
            else if (product === 'MPC') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Pacific-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MPC';
            else if (product === 'MPJ') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Pacific-ex-Japan-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MPJ';
            
            

            else if (product === 'MJP') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Japan-(JPY)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MJP';
            else if (product === 'MJJ') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Japan-Net-Total-Return-(JPY)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MJJ';
            else if (product === 'MSG') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Singapore-Free-(SGD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MSG';
            else if (product === 'TWN') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Taiwan-25-50-Net-Total-Return-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=TWN';
            else if (product === 'TWP') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/MSCI-Taiwan-25-50-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=TWP';
            
            else if (product === 'HTI') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-TECH-Index-Futures-and-Options/Hang-Seng-TECH-Index-Futures?sc_lang=' + that.sc_lang + '#&product=HTI';
            else if (product === 'PTE') 
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-TECH-Index-Futures-and-Options/Hang-Seng-TECH-Index-Futures-Options?sc_lang=' + that.sc_lang + '#&product=PTE';
            
            else if (product === 'PHS')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-Index-(HSI)/Hang-Seng-Index-Futures-Options?sc_lang=' + that.sc_lang + '#&product=PHS';
            else if (product === 'PHH')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/Hang-Seng-China-Enterprises-Index/Hang-Seng-China-Enterprises-Index-Futures-Options?sc_lang=' + that.sc_lang + '#&product=PHH';

            else if (product === 'MCA')
                window.location.href='/Products/Listed-Derivatives/Equity-Index/MSCI-Indexes/MSCI-Indexes/APAC-Emerging-Market-Single-Country/Price-Return/MSCI-China-A-50-Connect-(USD)-Index-Futures?sc_lang=' + that.sc_lang + '#&product=MCA';
            
            else if (product === 'CHI') 
                window.location.href='/products/listed-derivatives/equity-index/msci-indexes/msci-indexes/apac-emerging-market-single-country/price-return/msci-china-(usd)-index-futures?sc_lang=' + that.sc_lang + '#&product=CHI';
            else if (product === 'CHN') 
                window.location.href='/products/listed-derivatives/equity-index/msci-indexes/msci-indexes/apac-emerging-market-single-country/net-total-return/msci-china-net-total-return-(usd)-index-futures?sc_lang=' + that.sc_lang + '#&product=CHN';
        });

        //export to excel future
        that.$equity_future.find(".ete").on('click',function(){
            that._exportFutures();
        });
        
        //export to excel option
        that.$equity_option.find(".ete").on('click',function(e){
            that._eTTE('equity_option','xlsx',''+that.product+'_Options');
        });
        
        ////////////////////////////////////////////////////////////////////
        this.$scroll_tabs.scrollTabs();
        
        ////////////////////////////////////////////////////////////////////
        this.$hsirow.find(".hsichart .period").click(function(){
            $(this).addClass("selected").siblings().removeClass("selected");
            var c_rb = LabCI.WP.CommonRC.getMsg("interval", that.lang);
            var intervals = that.PAGEOBJ_RESOURCEBUNDLE.conf.intervals;
            var sup_int = that.PAGEOBJ_RESOURCEBUNDLE.conf.perintsetting[$(this).attr('id')];
            
            if (sup_int){
                that.$hsirow.find(".interval .period").detach();
                var arr = sup_int.split(',');
                for (var i=0; i<arr.length; i++){
                    var $item = $("<div/>").addClass("period").attr("id", intervals[arr[i]]).html(c_rb[intervals[arr[i]]]);
                    if (i === 0)
                        $item.addClass("selected");
                    $item.click(function(){
                        $(this).addClass("selected").siblings().removeClass("selected");
                        
                        that._dataChartExportFlow();
                    });
                    
                    that.$hsirow.find(".interval").append($item);
                }
                
                var span=that._getSelectedInterval();
                if(span > 6){
                    that.$hsirow.find(".hsichart").attr({"data-id": "6"});
                    that.$hsirow.find(".interval").attr({"data-id": "6"});
                }else{
                    that.$hsirow.find(".hsichart").attr({"data-id": that._getSelectedInterval()});
                    that.$hsirow.find(".interval").attr({"data-id":that._getSelectedSpan()});
                }
            }
            if (that.curdata){
                that._dataChartExportFlow();
            }
        });
        this.$hsirow.find(".hsichart .period").eq(0).click();
        
        var c_rb = LabCI.WP.CommonRC.getMsg("chart", that.lang);
        //  Highcharts 
        Highcharts.setOptions({
            global: {
                timezone: 'Asia/Hong_Kong'
            },
            lang: {
                numericSymbols: null,
                thousandsSep: ',',
                noData: c_rb['noData'],
                month: c_rb['months'],
                shortMonths: c_rb['short_months']
            }
        });
        
        this.$equity_option.find(".loadmore_update").click(function (ev) {
            var ev = ev||window.event;
            that.$equity_option.find(".select_items").toggle();
            if(that.$equity_option.find(".dropup").length === 1){
                that.$equity_option.find(".loadmore_update").removeClass("dropup");
                that.$equity_option.find(".loadmore_update").addClass("dropdown");
            }else{
                that.$equity_option.find(".loadmore_update").removeClass("dropdown");
                that.$equity_option.find(".loadmore_update").addClass("dropup");
            }
            $(document).on('click',function(){
            that.$equity_option.find(".select_items").css("display","none");
            that.$equity_option.find(".loadmore_update").removeClass("dropup");
            that.$equity_option.find(".loadmore_update").addClass("dropdown");
            }); 
            ev.stopPropagation();
        });
        this.$equity_option.find(".select_item").click(function (ev) {
            var ev = ev||window.event;
            var itemPrev;
            $(this).addClass("loaditem_select").siblings().removeClass("loaditem_select");
            that.$equity_option.find(".loadmore_update").removeClass("dropup");
            that.$equity_option.find(".loadmore_update").addClass("dropdown");
            that.loadMore_option = +$(this)[0].firstElementChild.innerHTML;
            itemPrev = that.$equity_option.find(".loadmore_update")[0].firstElementChild.innerHTML;
            if(that.loadMore_option !== itemPrev){
                that.num_option = 0;
                that.temp_option = 1;
                that._clickoptionload(that.option_result);
                that.$equity_option.find(".load").click();
                if(that.loadMore_option < that.option_result.data.optionlist.length){
                    that.$equity_option.find(".load").show();
                }
            }
            that.$equity_option.find(".select_items").css("display","none");
            that.$equity_option.find(".loadmore_update").html($(this).html());
        });
        ////////////////////////////////////////////////////////////////////

        // Prepare the resize function
        // ... this has to be created here, because when resize() is called, the "this" will be in a different context
        // ... hence, use "that" in the function scope here to build this resize() function
        // ... a bad trick, but works ;)
        this.resize = function() {
            that.$pageobj.delaycall("resize", function() {
                that.resizeImpl();
            }, 100);
        };

        ////////////////////////////////////////////////////////////////////

        return this; // chain this
    },

    ////////////////////////////////////////////////////////////////////

    resize: null,

    resizeImpl: function() {
        var that=this;
        
        var tprightW=that.$hsirow.find(".hsichart").width();
        if(tprightW>400){
            that.$hsirow.find(".scroll_tabs_container div.scroll_tab_inner li").css({
                "width":"10%",
                "margin-right":"3px",
                "margin-left":"3px",
                "padding":"0"
            });
        }else{
            that.$hsirow.find(".scroll_tabs_container div.scroll_tab_inner li").css({
                "width":"auto",
                "margin-right":"3px",
                "margin-left":"3px",
                "padding":"0 10px"
            });
        }
    },

    ////////////////////////////////////////////////////////////////////

    showImpl: function(statedata) {
        // Get ready
        $(window).resize(this.resize);
        this.resizeImpl();
        this._loadinfo();
        
        return this; // chain this
    },

    hideImpl: function() {
        var that = this;

        // Unbind the resize event
        $(window).off(_RESIZE_EVENT, this.resize);

        return this; // chain this
    },

    refreshImpl: function() {
        return this; // chain this
    },

    resetImpl: function() {
        return this; // chain this
    },

    ////////////////////////////////////////////////////////////////////

    getStateDataImpl: function() {
        return { };
    },

    ////////////////////////////////////////////////////////////////////

    _loadinfo: function(){
        var that = this;
        var lang=LabCI.getLang();
        if(this.lang==='en')
            lang='eng';
        else if(this.lang==='zh_HK')
            lang='chi';
        else if(this.lang==='chn')
            lang='chn';

        this.$pageobj.loaddata("getderivativesinfo","getderivativesinfo",{
            lang: lang,
            token: LabCI.getToken(),
            ats: this.product
        },
        function(result){
            var info = result.data.info;
            if(info){
                if(info.fut.d || info.fut.n){
                    if (!info.fut.d || !info.fut.n){
                        that.$equity_future.find(".listpane .hkex_scroll_tabs").hide();
                    }
                    
                    that._loadfutures();
                    that.$section_table.find(".equity_future").show();
                }
                
                if(info.opt){
                    that._loadOptionContracts();
                    that.$section_table.find(".equity_option").show();
                }
                
                if(info.sc){
                    that._loadstandcom();
                    that.$collist.find(".equity_sta").show();
                }
                
                if(info.tmc){
                    that._loadtailorcom();
                    that.$collist.find(".equity_tai").show();
                }
                
                if(info.weekly){
                    that.$section_table.find(".options h2").html(LabCI.WP.Derivative.getMsg("op", that.lang).weeOp).addClass("weeklyTag weekly").attr("data-ats",that.product+"W");
                    that.$section_table.find(".options").prepend("<h2 class='weeklyTag active'data-ats='"+that.product+"'>" + LabCI.WP.Derivative.getMsg("op", that.lang).monOp + "</h2>");
                    
                    that.$section_table.find(".weeklyTag").off().on("click",function(){
                        that.$section_table.find(".options .active").removeClass("active");
                        $(this).addClass("active");
                        var lStartVal = that.$optionsrow.find(".valstart").val().replace(/,/g,'');
                        var lEndVal = that.$optionsrow.find(".valend").val().replace(/,/g,'');
                        var lStart = Number(lStartVal);
                        var lEnd = Number(lEndVal);
                        
                        if ($(this).hasClass("weekly")){
                            that.$section_table.find(".mon").html(LabCI.WP.Derivative.getMsg("op",that.lang).expiry);
                            that._loadOptionContracts(that._inx,$(this).attr("data-ats"));
                        } else {
                            that.$section_table.find(".mon").html(LabCI.WP.Derivative.getMsg("op",that.lang).msmmon);
                            that._loadOptionContracts(that._inx,$(this).attr("data-ats"));
                        }
                    });
                    
                }
                
                if(info.rt){
                    that.$loadrow.find(".disclaimer").html(LabCI.WP.Derivative.getMsg("loadrow", that.lang).disclaimer.realtimeData);
                }else{
                    that.$loadrow.find(".disclaimer").html(LabCI.WP.Derivative.getMsg("loadrow", that.lang).disclaimer.delayedData);
                }  
            }
        },
        0,
        {
            datatype: "jsonp"
        });
    },
    _loadOptionContracts: function(inx, ats){
        if (!inx){
            inx = 0;
        }
        var that = this;
        var lang=LabCI.getLang();
        if(this.lang==='en')
            lang='eng';
        else if(this.lang==='zh_HK')
            lang='chi';
        else if(this.lang==='chn')
            lang='chn';

        this.$optionsrow.find(".sewvbm li").detach();
        
        if (ats)
            paramATS = ats;
        else 
            paramATS = this.product;

        this.$pageobj.loaddata("getoptioncontractlist", "getoptioncontractlist",
        {
            lang: lang,
            token: LabCI.getToken(),
            ats: paramATS,
            type: inx
        },
        function(result) {
            if (result && result.data && result.data.responseCode!=="F") {
                if (result.data.conlist){                    
                    //select month
                    that.$optionsrow.find(".sewvtop").off('click').on('click',function(){
                        $(this).next().slideToggle(150);
                        if($(this).find("em").hasClass("lbaxztop")){
                            $(this).find("em").addClass("lbaxztop2");
                            $(this).find("em").removeClass("lbaxztop");
                        }else{
                            $(this).find("em").addClass("lbaxztop");
                            $(this).find("em").removeClass("lbaxztop2");
                        }
                    });
                    
                    //mCustomScrollbar option
                    that.$opt.mCustomScrollbar({
                        axis:"x",
                        theme:"my",
                        advanced:{
                            autoExpandHorizontalScroll:true
                        },
                        scrollButtons:{
                            enable:true,
                            scrollType:"stepped"
                        },
                        mouseWheel:{deltaFactor:40}
                    });
            
                    $.each(result.data.conlist, function(index, value){
                        var $item  = $("<li/>").attr({'value': value.id}).html(value.mon);
                        
                        $item.on('click',function(){
                            that.$optionsrow.find(".sewvtop>span").attr({"value": value.id}).text(value.mon);
                            $(this).parent("ul").hide();
                            that.$opt.find(".month_day").html(value.mon.toUpperCase());
                            if(that.$optionsrow.find("em").hasClass("lbaxztop")){
                                that.$optionsrow.find("em").addClass("lbaxztop2");
                                that.$optionsrow.find("em").removeClass("lbaxztop");
                            }else{
                                that.$optionsrow.find("em").addClass("lbaxztop");
                                that.$optionsrow.find("em").removeClass("lbaxztop2");
                            }
                            
                            that._loadOptionData(inx, null,null,null, paramATS);
                        });
                        
                        that.$optionsrow.find(".sewvbm").append($item);
                    });
                    
                    that.$optionsrow.find(".sewvbm li")[0].click();
                }
            }
        },
        0,
        {
            datatype: "jsonp"
        });
    },
    option_result: null,
    _loadOptionData: function(inx, from, to, keepslider, ats){
        
        if (!inx){
            inx = '0';
        }
        this._inx = inx;
        var that = this;
        var lang=LabCI.getLang();
        if(this.lang==='en')
            lang='eng';
        else if(this.lang==='zh_HK')
            lang='chi';
        else if(this.lang==='chn')
            lang='chn';

        var con = this.$optionsrow.find(".sewvtop>span").attr("value");

        this.$overflowrow.find(".tdrow_dataList1 table#option tbody tr").detach();
        this.$equity_option.find(".lastupdated .data_last").setValue("-");

        if (!ats)
            paramATS = this.product;
        else 
            paramATS = ats;
        this.$pageobj.loaddata("getderivativesoption", "getderivativesoption",
        {
            lang: lang,
            token: LabCI.getToken(),
            ats: paramATS,
            con: con,
            fr: from ? from: null,
            to: to ? to: null,
            type: inx
        },
        function(result) {
            if (result && result.data && result.data.responseCode!=="F") {
                if (result.data.optionlist){
                    var count = result.data.optionlist;
                    that.option_result = result;
                    if(count.length>20){
                        var j=20;
                    }else{
                        var j=count.length;
                        that.$equity_option.find(".load").hide();
                    }
                    for(var i=0;i<j;i++){
                        that.$overflowrow.find(".tdrow_dataList1 table#option tbody").append(that._loadmoreOptionHtml(result.data.optionlist,i));
                    }
                    if (result.data.lastupd && result.data.lastupd !== '' && result.data.lastupd !== '-') 
                        that.$equity_option.find(".lastupdated .data_last").setValue(that._dateFormat(result.data.lastupd), " HKT");
                    var start = Number(LabCI.Utils.removeCommaSeparators(result.data.optionlist[0].strike));
                    var end = Number(LabCI.Utils.removeCommaSeparators(result.data.optionlist[result.data.optionlist.length-1].strike));
                    var min = Number(LabCI.Utils.removeCommaSeparators(result.data.min));
                    var max = Number(LabCI.Utils.removeCommaSeparators(result.data.max));
                    
                    //noUiSlider
                    var slider1 = document.getElementById('slider');
                    
                    //min and max cannot be equal.
                    if(min === max){
                        that.$optionsrow.find(".mss").hide();
                        return;
                    }
                    
                    that.$optionsrow.find(".mss").show();
                    if (!keepslider && slider1.noUiSlider)
                        slider1.noUiSlider.destroy();

                    if (!slider1.noUiSlider){
                        noUiSlider.create(slider1, {
                            handles: 2,
                            start: [start, end],
                            connect: true,
                            orientation:'horizontal',
                            range: {
                                'min': min,
                                'max': max
                            },
                            tooltips: true,
                            format: wNumb({
                                decimals: 0,
                                thousand: ','
                            }),
                            pips: { // Show a scale with the slider
                                mode: 'values',
                                values: [min, max],
                                stepped: true,
                                density: 2,
                                format: wNumb({
                                    decimals: 0,
                                    thousand: ','
                                })
                            }
                            // step: 100

                        });
                        
                        //change value
                        var dateValues = [
                            that.$optionsrow.find(".valstart")[0],
                            that.$optionsrow.find(".valend")[0]
                        ];
                        that.$optionsrow.find("input.mss_list").bind("change",function(){
                            var lStartVal = that.$optionsrow.find(".valstart").val().replace(/,/g,'');
                            var lEndVal = that.$optionsrow.find(".valend").val().replace(/,/g,'');
                            var lStart = Number(lStartVal);
                            var lEnd = Number(lEndVal);
                            that._loadOptionData(that._inx, lStart, lEnd, true, paramATS);
                            that.$optionsrow.find("#slider")[0].noUiSlider.set([lStart, lEnd]);
                            that.$equity_option.find(".load").show();
                        });
                        that.$optionsrow.find("#slider")[0].noUiSlider.on('update', function(values, handle){
                            var lStart = Number(values[0].replace(/,/g,''));
                            var lEnd = Number(values[1].replace(/,/g,''));
                            dateValues[handle].value = values[handle];
                        });
                        that.$optionsrow.find("#slider")[0].noUiSlider.on('change', function(values, handle){
                            var lStart = Number(values[0].replace(/,/g,''));
                            var lEnd = Number(values[1].replace(/,/g,''));
                            that.$equity_option.find(".load").show();
                            dateValues[handle].value = values[handle];
                            that._loadOptionData(that._inx, lStart, lEnd, true, paramATS);
                        });
                    }
                }
                that.num_option = 1;
                that._clickoptionload(result);
                
                //export options
                that._loadOptionExportData(inx,min,max, paramATS);
            }
        },
        0,
        {
            datatype: "jsonp"
        });
    },
    
    _initchart: function() {
        this.force_ddMMM = false;
        this.force_MMMyy = false;
        this.$chartbox = this.$hsirow.find(".hsichart .chartbox").highcharts('StockChart', {
            chart: {
                panning: false,
                pinchType: 'none'
            },
            rangeSelector: {
                enabled: false
            },
            navigator: {
                enabled: false
            },
            scrollbar: {
                enabled: false
            },
            credits:{
                enabled: false
            },
            title: {
                text: null
            },
            tooltip: {
                crosshairs: [{
                    width: 1,
                    color: 'gray',
                    dashStyle: 'dot',
                    zIndex: 22
                }],
                padding: 5,
                positioner:function(labelWidth, labelHeight, point){
                    var x = point.plotX;
                    var chart = this.chart;

                    if (x - labelWidth/2 < - chart.plotLeft)
                        x  = 0;
                    else if ((x + labelWidth) > (chart.plotLeft + chart.plotWidth))
                        x -= (x + labelWidth) - (chart.plotLeft + chart.plotWidth);
                    
                    return {x : x, y : 0};
                },
                formatter: function () {
                    return Highcharts.numberFormat(this.y, 2) + ' (' +Highcharts.dateFormat('%H:%M', new Date(this.x)) +')';
                }
            },
            exporting: {
                enabled: false
            },
            plotOptions: {
                series: {
                    animation: {
                        duration: 2000,
                        easing: 'easeOutBounce'
                    }
                }
            },
            series: [{
                name: '',
                yAxis: 0,
                type: 'area',
                threshold: null,
                tooltip: {
                    valueDecimals: 2
                },
                color: '#7AC1E4',
                lineWidth: 1,
                fillColor: 'rgba(180,222,242, 0.75)',
                marker: {
                    states: {
                        hover: {
                            fillColor: "#FF0000",
                            radiusPlus: 2
                        }
                    }
                },
                datagrouping: {
                    enabled: false
                }
            }],
            yAxis: [{
                opposite: false,
                labels: {
                    style: {
                        "color": "#13426B"
                    },
                    y: 4
                },
                gridLineColor: "#EDEDED",
                gridLineWidth: 1,
                startOnTick: true,
                endOnTick: true,
                showLastLabel: true,
                tickAmount: 5
            }],
            xAxis: {

                lineColor: "#13426B",
                labels: {
                    style: {
                    "color": "#13426B"
                    },
                    formatter: function(){
                        return Highcharts.dateFormat('%H:%M', new Date(this.value));
                    }
                },
                tickColor: "#13426B",
                tickPosition: 'inside',
                tickLength: 5,
                zIndex: 22,
                startOnTick: false,
                ordinal: false,
                tickPositioner: function(){
                    var positions = [],
                        tick = Math.floor(this.min);

                    var start_date = new Date(tick);
                    start_date.set({minute: 0});

                    if (this.max !== null && this.min !== null) {
                        while (start_date.getTime() <= this.max){
                            positions.push(start_date.getTime());
                            start_date.add({hours: 1});
                        }
                    }

                    return positions;
                }
            }
        });
        this.$chartbox.highcharts().hideNoData();
    },

    _getSelectedSpan: function() {
        var sel = this.$hsirow.find(".interval .period.selected").attr("id");
        if (sel === 'min')
            return 0;
        else if (sel === 'min5')
            return 2;
        else if (sel === 'min15')
            return 3;
        else if (sel === 'hourly')
            return 5;
        else if (sel === 'daily')
            return 6;
        else if (sel === 'weekly')
            return 7;
        else if (sel === 'monthly')
            return 8;
        else if (sel === 'quarterly')
            return 9;
    },

    _getSelectedInterval: function() {
        var sel = this.$scroll_tabs.find(".period.selected").attr("id");
        if  (sel === 'p1d')
            return 0;
        else if (sel === 'p5d')
            return 1;
        else if (sel === 'p1m')
            return 2;
        else if (sel === 'p3m')
            return 3;
        else if (sel === 'p6m')
            return 4;
        else if (sel === 'p1y')
            return 5;
        else if (sel === 'p2y')
            return 6;
        else if (sel === 'p5y')
            return 7;
        else if (sel === 'p10y')
            return 8;
        else if (sel === 'ytd')
            return 9;
    },

    _showchart: function(ric, pClose) {
        var that = this;
        if (!ric)
            return;
        
        this.chartric = ric;
        this.chartpClose = pClose;
        
//      if (!this.$chartbox)
        this._initchart();
        
        this.$chartbox.highcharts().yAxis[0].removePlotLine('pClose');
        this.$chartbox.highcharts().yAxis[0].setExtremes(null, null);
        this.$chartbox.highcharts().hideNoData();
        
        this.$pageobj.loaddata("getchartdata2", "getchartdata2",
        {
            "hchart": 1,
            "span": that._getSelectedSpan(),
            "int": that._getSelectedInterval(),
            "ric": ric,
            "token": LabCI.getToken()
        },
        function(result) {
            if (result && result.data) {
                var $chart = that.$chartbox.highcharts();

                var start_h = result.data.start_h;
                var start_m = result.data.start_m;
                var end_h = result.data.end_h;
                var end_m = result.data.end_m;

                var weekend_fr = Date.UTC(2010, 0, 1, end_h, end_m  + 1, 0, 0);
                var weekend_to = Date.UTC(2010, 0, 4, start_h, start_m - 1, 0, 0);
                
                var night_fr = Date.UTC(2010, 1, 3, end_h, end_m  + 1, 0, 0);
                var night_to = Date.UTC(2010, 1, 4, start_h, start_m - 1, 0, 0);

                if (that._getSelectedSpan() < 6){
                    if (that._getSelectedSpan() === 5){
                        weekend_fr = Date.UTC(2010, 0, 1, end_h, end_m  + 1, 0, 0);
                        weekend_to = Date.UTC(2010, 0, 4, start_h-1, 59, 0, 0);
                        night_fr = Date.UTC(2010, 1, 3, end_h, end_m  + 1, 0, 0);
                        night_to = Date.UTC(2010, 1, 4, start_h-1, 59, 0, 0);
                    }  
                    var format = '%H:%M';

                    if (that._getSelectedInterval() === 1)
                        format = '%m/%d %H:%M';

                    $chart.tooltip.options.formatter = function() {
                        return Highcharts.numberFormat(this.points[0].y, 2) + ' (' +Highcharts.dateFormat(format, new Date(this.x)) +')';
                    };

                    var breaks = [{ // Weekends
                        from: weekend_fr,
                        to: weekend_to,
                        repeat: 7 * 24 * 36e5
                    }
                    ,{
                        from: Date.UTC(2017, 3, 14, start_h, start_m, 0, 0),
                        to: Date.UTC(2017, 3, 14, end_h, end_m, 0, 0)
                    }
                    ,{
                        from: Date.UTC(2017, 3, 17, start_h, start_m, 0, 0),
                        to: Date.UTC(2017, 3, 17, end_h, end_m, 0, 0)
                    }
                    ];

                    if (night_to.valueOf() - night_fr.valueOf() < 86340000){
                        breaks.push({ // Nights
                            from: night_fr,
                            to: night_to,
                            repeat: 24 * 36e5
                        });
                    }

                    $chart.xAxis[0].update({breaks :breaks});
                    $chart.hideNoData();
                    if (result.data.datalist){
                        $chart.xAxis[0].setExtremes(result.data.datalist[0][0], result.data.datalist[result.data.datalist.length-1][0]);
                        $chart.hideNoData();
                    }
                    if (that._getSelectedInterval() === 0){  // 1 Day
                        
                    
                    }else{  // 5 Day
                        $chart.xAxis[0].update({tickPositioner: function(){
                            var positions = [],
                                tick = Math.floor(this.min);

                            var start_date = new Date(tick);
                            start_date.set({hour: start_h + 8, minute: start_m});

                            if (this.max !== null && this.min !== null) {
                                while (start_date.getTime() <= this.max){
                                    positions.push(start_date.getTime());
                                    start_date.add({days: 1});
                                }
                            }
                            return positions;
                        }});
                        $chart.hideNoData();
                    }
                    if (that._getSelectedInterval() === 1){
                        $chart.xAxis[0].update({labels: {
                            style: {
                            "color": "#13426B"
                            },
                            formatter: function(){
                                return Highcharts.dateFormat(that.ddMMMformat, new Date(this.value));
                            }
                        }
                        });
                        $chart.hideNoData();
                    }
                }else{
                    $chart.xAxis[0].update({labels: {
                        style: {
                        "color": "#13426B"
                        },
                        formatter: function(){
                            if (result.data.datalist.length >= 3 && result.data.datalist[result.data.datalist.length-2][0] - result.data.datalist[1][0] > 31556952000){
                                return Highcharts.dateFormat(that.MMMyyformat, new Date(this.value));
                            }else if (that.force_MMMyy){
                                return Highcharts.dateFormat(that.MMMyyformat, new Date(this.value));
                            }else if (!that.force_ddMMM && (that._getSelectedInterval() === 6 || that._getSelectedInterval() === 7)){
                                return Highcharts.dateFormat(that.MMMyyformat, new Date(this.value));
                            }else if (!that.force_ddMMM && that._getSelectedInterval() === 8)
                                return Highcharts.dateFormat('%Y', new Date(this.value));
                            else
                                return Highcharts.dateFormat(that.ddMMMformat, new Date(this.value));
                            }
                        }
                    });
                    $chart.hideNoData();
                    
                    $chart.xAxis[0].update({tickPositioner: function(){
                        var positions = [],
                            tick = Math.floor(this.dataMin);
                            
                        if (result.data.datalist.length === 2)
                            return positions;

                        var date = new Date(tick);
                        if (that._getSelectedInterval() === 2 || that._getSelectedInterval() === 3){ // 1 Month or 3 Months
                            date.moveToDayOfWeek(1, -1).setHours(0);
                            if (this.dataMax !== null && this.dataMin !== null) {
                                while (date.getTime() <= this.dataMax){
                                    date.add({days: 7});
                                    positions.push(date.getTime());
                                }
                            }
                        }else if (that._getSelectedInterval() === 5 || that._getSelectedInterval() === 6){    // 1 Year or 2 Year
                            date.set({month: 0, day: 1}).setHours(0);
                            if (this.dataMax !== null && this.dataMin !== null) {
                                while (date.getTime() <= this.dataMax){
                                    date.addMonths(3);
                                    positions.push(date.getTime());
                                }
                            }
                        }else if (that._getSelectedInterval() === 7 || that._getSelectedInterval() === 8){    // 5 Year or 10 Year
                            date.set({month: 0, day: 1}).setHours(0);
                            if (this.dataMax !== null && this.dataMin !== null) {
                                while (date.getTime() <= this.dataMax){
                                    date.addYears(1);
                                    positions.push(date.getTime());
                                }
                            }
                        }else {
                            date.set({day: 1}).setHours(0);
                            if (this.dataMax !== null && this.dataMin !== null) {
                                while (date.getTime() <= this.dataMax){
                                    date.addMonths(1);
                                    positions.push(date.getTime());
                                }
                            }
                        }
                        
                        if (positions.length > 0 && $(window).width() <= 1000){
                            if (positions.length > 4 && (that._getSelectedInterval() === 6 || that._getSelectedInterval() === 7 || that._getSelectedInterval() === 8))
                                that.force_MMMyy = true;
                            var s = Math.max(Math.ceil(positions.length/3), 1);
                            var pos = [] ;
                            for (var i=0; i<positions.length; i+=s){
                                pos.push(positions[i]);
                            }
                            positions = pos;
                        }
                        
                        if (($(window).width() > 1000 && positions.length <= 5) || ($(window).width() < 1000 && positions.length <= 4)){
                            positions = [];
                            var last = result.data.datalist.length - 1;
                            if (that._getSelectedSpan() >= 6){
                                if (that._getSelectedSpan() >= 8 && result.data.datalist.length >= 6)
                                    last = result.data.datalist.length - 3;
                                else if (!result.data.datalist[result.data.datalist.length - 1][1])
                                    last = result.data.datalist.length - 2;
                            }
                            
                            if (result.data.datalist.length < 8) {
                                for (var i=0; i<=last; i++){
                                    var date = new Date(result.data.datalist[i][0]);
                                    positions.push(date.getTime());
                                }
                            }else {
//                                var step = Math.floor(Math.floor((result.data.datalist[last][0] - result.data.datalist[1][0]) / 86400000) / 5);
                                var sector = $(window).width() < 1000 ? 3 : 5;
                                var step = Math.floor(Math.floor((result.data.datalist[last][0] - result.data.datalist[1][0]) / 86400000) / sector);
                                var date = new Date(result.data.datalist[last][0]);
                                date.setHours(0);
                                var start = new Date(result.data.datalist[1][0]);
                                while (date >= start){
                                    positions.push(date.getTime());
                                    date.addDays(-step);
                                }
                            }
                            that.force_ddMMM = true;
                        }else {
                            that.force_ddMMM = false;
                        }
                        
                        return positions;
                    }});
                    $chart.hideNoData();
                    
                    $chart.tooltip.options.formatter = function() {
                        return Highcharts.numberFormat(this.y, 2) + ' (' +Highcharts.dateFormat('%m/%d/%Y', new Date(this.x)) +')';
                    };

                }

                var close = [];
                var min = parseFloat(LabCI.Utils.removeCommaSeparators(pClose));
                var max = parseFloat(LabCI.Utils.removeCommaSeparators(pClose));

                for (var i=1; result.data.datalist && i<result.data.datalist.length; i++){
                    var val = result.data.datalist[i][4];
                    if (!val && result.data.datalist.length === 2){
                        continue;
                    }
                    
                    var f = parseFloat(val);
                    if (isNaN(min))
                        min = f;
                    else if (f < min)
                        min = f;
                        
                    if (isNaN(max))
                        max = f;
                    else if (f > max)
                        max = f;

                    close.push([result.data.datalist[i][0], val]);
                }

                if (!isNaN(min) || !isNaN(max)){
                    $chart.yAxis[0].setExtremes(min,max);
                    $chart.hideNoData();
                }
//                $chart.series[0].setData(close, false);

                var series = {
                        name: '',
                        yAxis: 0,
                        type: 'area',
                        threshold: null,
                        tooltip: {
                            valueDecimals: 2
                        },
                        color: '#7AC1E4',
                        lineWidth: 1,
                        fillColor: 'rgba(180,222,242, 0.75)',
                        marker: {
                            states: {
                                hover: {
                                    fillColor: "#FF0000",
                                    radiusPlus: 2
                                }
                            }
                        },
                        data: close,
                        dataGrouping: {
                            enabled: false
                        }
                    };

                $chart.series[0].remove();
                $chart.addSeries(series);
                
                
                var labely = 15;
                var pClose_value = parseFloat(LabCI.Utils.removeCommaSeparators(pClose));
                
                var axisy = $chart.yAxis[0].toPixels($chart.yAxis[0].min, false);
                var liney = $chart.yAxis[0].toPixels(pClose_value, false);
                
                if (axisy - liney < 60)
                    labely = -15;

                var c_rb = LabCI.WP.CommonRC.getMsg("chart", that.lang);
                $chart.yAxis[0].addPlotLine({
                    id: 'pClose',
                    value: LabCI.Utils.removeCommaSeparators(pClose),
                    color: '#13426B',
                    dashStyle: 'dot',
                    width: 1,
                    label: {
                        align: 'right',
                        text: c_rb['pclose'] + '<br/>' + pClose,
                        useHTML: true,
                        style: {
                            "color": "#13426B",
                            "line-height": "14px",
                            "font-size": '0.875rem'
                        },
                        x: -20,
                        y: labely
                    },
                    zIndex: 22
                });

//                $chart.redraw();
            }else{
                var $chart = that.$chartbox.highcharts();
//                $chart.series[0].setData([]);
                $chart.series[0].remove();
                $chart.showNoData();
            }
        },
        0,
        {
            datatype: "jsonp"
        });
    },
    
    _loadstandcom: function(){
        var that=this;
        var lang=LabCI.getLang();
        if(this.lang==='en'){
            lang='eng';
        }
        else if(this.lang==='zh_HK'){
            lang='chi';
        }
        else if(this.lang==='chn'){
            lang='chn';
        }
        
        this.$pageobj.loaddata("getstandardcom", "getstandardcom",
        {
            lang: lang,
            token: LabCI.getToken(),
            ats: this.product
        },
        function(result) {
            if (result && result.data && result.data.responseCode!=="F") {
                if (result.data.lastupd && result.data.lastupd !== '' && result.data.lastupd !== '-')
                    that.$collist.find(".equity_sta .loadrow .data_last").setValue(that._dateFormat(result.data.lastupd), " HKT");
                
                that._showStaTai(result.data.riclist,0);
            }
        },
        0,
        {
            datatype: "jsonp"
        });   
     },
    _loadtailorcom: function(){
        var that=this;
        var lang=LabCI.getLang();
        if(this.lang==='en'){
            lang='eng';
        }
        else if(this.lang==='zh_HK'){
            lang='chi';
        }
        else if(this.lang==='chn'){
            lang='chn';
        }
        
        this.$pageobj.loaddata("gettailormade", "gettailormade",
        {
            lang: lang,
            token: LabCI.getToken(),
            ats: this.product
        },
        function(result) {
            if (result && result.data && result.data.responseCode!=="F") {
                if (result.data.lastupd && result.data.lastupd !== '' && result.data.lastupd !== '-')
                    that.$collist.find(".equity_tai .loadrow .data_last").setValue(that._dateFormat(result.data.lastupd), " HKT");
                
                that._showStaTai(result.data.tmclist,1);
            }
        },
        0,
        {
            datatype: "jsonp"
        });   
     },
    _loadfutures: function(inx){
        if (!inx)
            inx = '0';
        var that=this;
        var lang=LabCI.getLang();
        if(this.lang==='en'){
            lang='eng';
        }
        else if(this.lang==='zh_HK'){
            lang='chi';
        }
        else if(this.lang==='chn'){
            lang='chn';
        }
        
        this.$pageobj.loaddata("getderivativesfutures", "getderivativesfutures",
        {
            lang: lang,
            token: LabCI.getToken(),
            ats: this.product,
            type: inx
        },
        function(result) {
            if (result && result.data && result.data.responseCode!=="F") {
                that.curdata = result.data;

                if (result.data.lastupd && result.data.lastupd !== '' && result.data.lastupd !== '-') 
                    that.$equity_future.find(".lastupdated .data_last").setValue(that._dateFormat(result.data.lastupd), " HKT");
                if(result.data.futureslist.length>0){
                    that.$sec_max.next().css("display","block");
                    that.$sec_max.css("display","block");
                    that.$section_table.find(".equity_data_table").css("min-height","315px");
                    that._loaddata(result,inx);
                }else{
                    that.$sec_max.next().css("display","none");
                    that.$sec_max.css("display","none");
                    that.$section_table.find(".equity_data_table").css("min-height","0px");
                }
                
            }
        },
        0,
        {
            datatype: "jsonp"
        });   
    },
    
    _inx:0,
    loadMore_option: 20,
    num_option: 0,
    temp_option:null,
    loadMore_future: 20,
    num_future: 0,
    temp_future:null,
    _loaddata: function(data,inx) {
        var that = this;
        var index = 0;
        var result = { data: {
            responseCode: "S"
        }};

        if (data) {
            // Fit the data into the UI
            that._showindexquote(data);
            
            //mCustomScrollbar 
            that.$sec_max.mCustomScrollbar({
                axis:"x",
                theme:"my",
                advanced:{
                    autoExpandHorizontalScroll:true
                },
                scrollButtons:{
                    enable:true,
                    scrollType:"stepped"
                },
                mouseWheel:{deltaFactor:40}
            });
            
            //scroll_tabs
            if(inx===0){
                this.$scroll_tabs.find(".scroll_tabs_ds").addClass("scroll_tabs_ds_hover");
                this.$scroll_tabs.find(".scroll_tabs_ns").addClass("scroll_tabs_ns");
            }
            this.$scroll_tabs.find(".scroll_tabs_ns").off('click').on('click',function(){
                this._inx =1;
                that._loadfutures(this._inx);
                that._loadOptionContracts(this._inx);
                
                that.$section_table.find(".options h2.active").removeClass("active");
                that.$section_table.find(".options h2:eq(0)").addClass("active");
                
                that._loadOptionData(this._inx);
                $(this).removeClass().addClass("scroll_tabs_ns_hover");
                $(this).siblings().removeClass().addClass("scroll_tabs_ds");
            });
            this.$scroll_tabs.find(".scroll_tabs_ds").off('click').on('click',function(){
                this._inx =0;
                that._loadfutures(this._inx);
                that._loadOptionContracts(this._inx);
                
                that.$section_table.find(".options h2.active").removeClass("active");
                that.$section_table.find(".options h2:eq(0)").addClass("active");
                
                that._loadOptionData(this._inx);
                $(this).removeClass().addClass("scroll_tabs_ds_hover");
                $(this).siblings().removeClass().addClass("scroll_tabs_ns");
            });
            //hsirow
            var sec_title_top = that.$equity_future.find("thead tr").outerHeight();
            var sec_td_top = (index+1)*that.$equity_future.find("tbody tr").outerHeight();
            var hsirow_top = that.$equity_future.find(".hsirow").outerHeight();
            this.$sec_max.find("tbody tr").eq(0).after("<tr class='hsirowcon'></tr>");
            this.$sec_max.next().css({"top":"100px"});            
            this.$sec_max.find("tbody tr")[0].click();
            this.$section_table.find(".mCSB_buttonRight").css("top",sec_title_top+sec_td_top+(hsirow_top/2)+"px");
            this.$section_table.find(".mCSB_buttonLeft").css("top",sec_title_top+sec_td_top+(hsirow_top/2)+"px");
            
            this.$collist.find(".equity_sta .mCSB_buttonRight").css("top","150px");
            this.$collist.find(".equity_sta .mCSB_buttonLeft").css("top","150px");
            
            //Standard Combinations
            this.$collist.find(".equity_standard").off('click').on('click',function(){
                if(that.$overflowrow.find(".sta_data_list").is(":hidden")){
                    that.$overflowrow.find(".sta_data_list").show();
                    that.$collist.find(".equity_sta .loadrow").show();
                    $(this).find(".ico1").css("transform","rotate(180deg)");
                }else{
                    that.$overflowrow.find(".sta_data_list").hide();
                    that.$collist.find(".equity_sta .loadrow").hide();
                    $(this).find(".ico1").css("transform","rotate(0deg)");
                }
            });
            
            //Tailor Made Combinations
            this.$collist.find(".equity_tailor").off('click').on('click',function(){
                if(that.$overflowrow.find(".tai_data_list").is(":hidden")){
                    that.$overflowrow.find(".tai_data_list").show();
                    that.$collist.find(".equity_tai .loadrow").show();
                    $(this).find(".ico2").css("transform","rotate(180deg)");
                }else{
                    that.$overflowrow.find(".tai_data_list").hide();
                    that.$collist.find(".equity_tai .loadrow").hide();
                    $(this).find(".ico2").css("transform","rotate(0deg)");
                }
            });

        }
        else {
            // alert(2);
            // Error handling...
        }

        return this; // chain this
    },
    _showindexquote: function(data) {
        var that = this;
        var result = data.data.futureslist;
        var html = '';
        that.$overflowrow.find(".future_data table#equity_future tbody tr").detach();
        that.$loadrow.find(".lastupdated .data").setValue("-");
        
        if(result.length>20){
            var j=20;
        }else{
            var j=result.length;
            that.$equity_future.find(".load").hide();
        }
        vo = 0;
        oi = 0;
        
        for(var i=0;i<j;i++){ 
            that.$overflowrow.find(".future_data table#equity_future tbody").append(that._loadmoreFutureHtml(result,i));
            if (result[i].vo != "")
                vo += Number(result[i].vo.replace(/\D/g,''));
            if (result[i].oi != "")
                oi += Number(result[i].oi.replace(/\D/g,''));
        };
        
		total_html="<tr class='total_row'>"+
            '<td>'+LabCI.WP.Derivative.getMsg("hsirow",LabCI.getLang()).total+'</td>'+
            '<td></td>'+
            '<td></td>'+
            '<td></td>'+
            '<td></td>'+
            '<td></td>'+
            '<td></td>'+
            '<td>'+vo.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")+'</td>'+
            '<td>'+oi.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")+'</td>'+
        "</tr>";
		that.$overflowrow.find(".total_row").remove();
		that.$overflowrow.find(".future_data table#equity_future thead").append(total_html)
        
        that._clickfutureload(data);
        that._futureRow(data);
        
        this.$overflowrow.find(".future_data tbody tr").each(function(index,el) {
            var el = $(el).find("td:eq(2)");
            if (el.text() !== '-'){
                if(el.text().indexOf("+") === 0) {
                    el.css("color","#24803D");
                } else  if(el.text().indexOf('-') === 0) {
                    el.css("color","#e72742");
                } 
            }else
                el.css("color","");  
        });

        if (data.data.lastupd && data.data.lastupd !== '' && data.data.lastupd !== '-') 
            that.$loadrow.find(".lastupdated .data").setValue(that._dateFormat(data.data.lastupd), " HKT");

        return this; // chain this
    },
    _dateFormat: function (data) {
        var res = /\/\d+\//;
        var res_reverse = data.split(" ")[0].split("/").reverse().join("/");
        var monthStr;
        var date_format;
        if(this.lang === "en"){
            switch(+data.split("/")[1])
            {
                case 1:
                    monthStr = "Jan";
                    break;
                case 2:
                    monthStr = "Feb";
                    break;
                case 3:
                    monthStr = "Mar";
                    break;
                case 4:
                    monthStr = "Apr";
                    break;
                case 5:
                    monthStr = "May";
                    break;
                case 6:
                    monthStr = "Jun";
                    break;
                case 7:
                    monthStr = "Jul";
                    break;
                case 8:
                    monthStr = "Aug";
                    break;
                case 9:
                    monthStr = "Sep";
                    break;
                case 10:
                    monthStr = "Oct";
                    break;
                case 11:
                    monthStr = "Nov";
                    break;
                case 12:
                    monthStr = "Dec";
                    break;
            }
            date_format =  data.replace(res," "+monthStr+" ");
        }else{
            date_format = res_reverse.replace(res,"年"+data.split("/")[1]+"月")+"日"+data.split(" ")[1];
        }
        return date_format;
    },
    _showfuturehsirow: function(data,index){
        var that = this;
        
        this.$hsirow.find(".con_l").html(data.data.futureslist[index].con_l);
        this.$hsirow.find(".ls").html(data.data.futureslist[index].ls);
        this.$hsirow.find(".nc").html(this._filtersVal(data.data.futureslist[index].nc)+' ');
        this.$hsirow.find(".pc").html('('+this._filtersVal(data.data.futureslist[index].pc)+'%'+')');

        this.$hsirow.find(".hi").setValue(data.data.futureslist[index].hi);
        this.$hsirow.find(".lo").setValue(data.data.futureslist[index].lo);
        this.$hsirow.find(".vo").setValue(data.data.futureslist[index].vo);
        //
        this.$hsirow.find(".hsibox div").each(function(index,el) {
            if ($(el).text() !== '- (-%)'){
                if($(el).text().indexOf("+") === 0) {
                    $(el).css("color","#24803D");
                } else  if($(el).text().indexOf('-') === 0) {
                    $(el).css("color","#e72742");
                }
            }else
                $(el).css("color","");
        });
        
        this._showchart(data.data.futureslist[index].ric, data.data.futureslist[index].hc);
    },
    _showStaTai : function(result,flag){
        var that = this;
//        var html='';
        for(var i=0;i<result.length;i++){
            let html = $('<tr/>');
//            html+='<tr>'+
//                '<td>'+this._filtersVal(result[i].con)+'</td>';
//                if(flag === 0){
//                    html+='<td><span>'+this._filtersVal(result[i].type)+'</span></td>'+
//                        "<td>"+this._filtersVal(result[i].legs)+"</td>";
//                }else{
//                    html+='<td><span>'+this._filtersVal(result[i].legs[0])+'</span><span>'+this._filtersVal(result[i].legs[1])+'</span></td>';
//                }
//                html+='<td>'+this._filtersVal(result[i].ls)+'</td>'+
//                '<td>'+this._filtersVal(result[i].bd)+'</td>'+
//                '<td>'+this._filtersVal(result[i].as)+'</td>'+
//                '<td>'+this._filtersVal(result[i].hi)+'</td>'+
//                '<td>'+this._filtersVal(result[i].lo)+'</td>'+
//                '<td>'+this._filtersVal(result[i].vo)+'</td>'+
//            "</tr>";
    
            html.append($('<td/>').html(this._filtersVal(result[i].con)));
            if (flag === 0) {
                html.append($('<td/>').append($('<span/>').html(this._filtersVal(result[i].type))));
                html.append($('<td/>').html(this._filtersVal(result[i].legs)));
            }else {
                let legsTD = $('<td/>');
                for (let j=0; j<result[i].legs.length; j++) {
                    legsTD.append($('<span/>').html(this._filtersVal(result[i].legs[j])));
                }
                html.append(legsTD);
            }
            html.append($('<td/>').html(this._filtersVal(result[i].ls)))
                .append($('<td/>').html(this._filtersVal(result[i].bd)))
                .append($('<td/>').html(this._filtersVal(result[i].as)))
                .append($('<td/>').html(this._filtersVal(result[i].hi)))
                .append($('<td/>').html(this._filtersVal(result[i].lo)))
                .append($('<td/>').html(this._filtersVal(result[i].vo)));
        
            if(flag === 0){
                that.$overflowrow.find(".sta_data_list .tdrow_dataList table tbody").append(html);
            }else{
                that.$overflowrow.find(".tai_data_list .tdrow_dataList2 table tbody").append(html);  
            }
        }
        
//        
//        if(flag === 0){
//            that.$overflowrow.find(".sta_data_list .tdrow_dataList table tbody").append(html);
//        }else{
//            that.$overflowrow.find(".tai_data_list .tdrow_dataList2 table tbody").append(html);  
//        }
            
        //mCustomScrollbar Standard Tailor
        that.$collist.find(".overflowrow").mCustomScrollbar({
            axis:"x",
            theme:"my",
            advanced:{
                autoExpandHorizontalScroll:true
            },
            scrollButtons:{
                enable:true,
                scrollType:"stepped"
            },
            mouseWheel:{deltaFactor:40}
        });
    },
    _futureRow :function(data){ 
        var that=this;
        
        //futures table hightcharts
        this.$sec_max.find("tbody tr:not(.total_row)").each(function(index,el){
            $(el).click(function(){
                var sec_title_top = that.$equity_future.find("thead tr").outerHeight();
                var sec_td_top = (index+2)*that.$equity_future.find("tbody tr").outerHeight();
                var hsirow_top = that.$equity_future.find(".hsirow").outerHeight();
                that.$sec_max.find(".mCSB_buttonRight").css("top",sec_title_top+sec_td_top+(hsirow_top/2)+"px");
                that.$sec_max.find(".mCSB_buttonLeft").css("top",sec_title_top+sec_td_top+(hsirow_top/2)+"px");
                that.$equity_future.find(".hsirow").css("top",sec_title_top+sec_td_top+1-20+"px");
                $(el).addClass("active").siblings().removeClass("active");
                $(el).siblings(".hsirowcon").remove();
                $(el).after("<tr class='hsirowcon'></tr>");
                
                that._showfuturehsirow(data,index);
                that.$equity_future.find("table#equity_future").attr("data-id",data.data.futureslist[index].ric);
            });
        });
    },
    _clickoptionload:function(result){
        var that = this;
        this.$equity_option.find(".load").off('click').on('click',function(){
            that.num_option = that.num_option+1;
            that._loadmoreOption(result,that.num_option);
        });
        this._isload=true; 
    },
    _clickfutureload:function(result){
        var that = this;   
        this.$equity_future.find(".load").off('click').on('click',function(){
            that.num_future = that.num_future+1;
            that._loadmoreFuture(result,that.num_future);
        }); 
        this._isload=true; 
    },
    
    _loadmoreOption: function(data,num) {
        var result = data.data.optionlist;
        var that=this;
        var max = num*that.loadMore_option;
        var min = max-that.loadMore_option;

        if(that.temp_option){
            that.$overflowrow.find(".tdrow_dataList1 table#option tbody").html("");
            that.temp_option = null;
        }
        if(isNaN(min)){
            that.$overflowrow.find(".tdrow_dataList1 table#option tbody").html("");
            for(var i=0; i<result.length; i++){
                that.$overflowrow.find(".tdrow_dataList1 table#option tbody").append(that._loadmoreOptionHtml(result,i));
            }
            that.$equity_option.find(".load").hide();
        }
        if(max < result.length){
            for(var i=min; i<max; i++){
                that.$overflowrow.find(".tdrow_dataList1 table#option tbody").append(that._loadmoreOptionHtml(result,i));
            }
        }else if(min < result.length || max > result.length){
            for(var i=min; i<result.length; i++){
                that.$overflowrow.find(".tdrow_dataList1 table#option tbody").append(that._loadmoreOptionHtml(result,i));
            }
            that.$equity_option.find(".load").hide();
        }
    },
    _loadmoreOptionHtml : function(result,i) {
        var $row = $('<tr/>').addClass('tdrow');
        $row.append($('<td/>').addClass('td').attr("headers","OI_Call Call").setValue(result[i].c.oi))
            .append($('<td/>').addClass('td').attr("headers","VO_Call Call").setValue(result[i].c.vo))
            .append($('<td/>').addClass('td').attr("headers","IV_Call Call").setValue(result[i].c.iv, '%'))
            .append($('<td/>').addClass('td bid').attr("headers","Bid_Ask_Call Call").setValue(this._filtersVal(result[i].c.bd)+" / "+this._filtersVal(result[i].c.as)))
            .append($('<td/>').addClass('td').attr("headers","Last_Call Call").setValue(result[i].c.ls))
            .append($('<td/>').addClass('td strike').attr("headers","Strike Call Put").setValue(result[i].strike))
            .append($('<td/>').addClass('td').attr("headers","Last_Put Put").setValue(result[i].p.ls))
            .append($('<td/>').addClass('td bid').attr("headers","Bid_Ask_Put Put").setValue(this._filtersVal(result[i].p.bd)+" / "+this._filtersVal(result[i].p.as)))
            .append($('<td/>').addClass('td').attr("headers","IV_Put Put").setValue(result[i].p.iv, '%'))
            .append($('<td/>').addClass('td').attr("headers","VO_Put Put").setValue(result[i].p.vo))
            .append($('<td/>').addClass('td').attr("headers","OI_Put Put").setValue(result[i].p.oi));
        return $row;
    },
    _loadOptionExportData : function(inx,from,to,ats) {
        if (!inx)
            inx = '0';
        var that = this;
        var lang=LabCI.getLang();
        if(this.lang==='en')
            lang='eng';
        else if(this.lang==='zh_HK')
            lang='chi';
        else if(this.lang==='chn')
            lang='chn';

        var con = this.$optionsrow.find(".sewvtop>span").attr("value");
        
        if (ats)
            paramATS = ats
        else 
            paramATS = this.product

        this.$pageobj.loaddata("getderivativesoption2", "getderivativesoption",
        {
            lang: lang,
            token: LabCI.getToken(),
            ats: paramATS,
            con: con,
            fr: from ? from: null,
            to: to ? to: null,
            type: inx
        },
        function(result) {
            if (result && result.data && result.data.responseCode!=="F") {
                if (result.data.optionlist){
                    var count = result.data.optionlist;
                    //clear export option
                    that.$overflowrow.find(".tdrow_dataList1 table#equity_option tbody tr").detach();
                    for(var i=0;i<count.length;i++){
                        //export option
                        that.$overflowrow.find(".tdrow_dataList1 table#equity_option tbody").append(that._loadmoreOptionHtmlExport(result.data.optionlist,i));
                    }
               }
           }
        },
        0,
        {
            datatype: "jsonp"
        });
    },
    _loadmoreOptionHtmlExport : function(result,i) {
        var html = '';
        html+='<tr>'+
            '<td>'+this._filtersVal(result[i].c.oi)+'</td>'+
            '<td>'+this._filtersVal(result[i].c.vo)+'</td>'+
            '<td>'+this._filtersVal(result[i].c.ls)+'</td>'+
            '<td class="strike">'+this._filtersVal(result[i].strike)+'</td>'+
            '<td>'+this._filtersVal(result[i].p.ls)+'</td>'+
            '<td>'+this._filtersVal(result[i].p.vo)+'</td>'+
            '<td>'+this._filtersVal(result[i].p.oi)+'</td>'+
        "</tr>";
        
        return html;
    },
    _loadmoreFuture: function(data,num) {
        var result = data.data.futureslist;
        var that=this;
        var html = "";
        var max = num*that.loadMore_future;
        var min = max-that.loadMore_future;
        if(that.temp_future){
            that.$overflowrow.find(".future_data table#equity_future tbody").html("");
        }
        if(isNaN(min)){
            for(var i=0; i<result.length; i++){
               that.$overflowrow.find(".future_data table#equity_future tbody").append(that._loadmoreFutureHtml(result,i));
            }
            that.$equity_future.find(".load").hide();
        }
        if(max < result.length){          
            for(var i=min; i<max; i++){
                that.$overflowrow.find(".future_data table#equity_future tbody").append(that._loadmoreFutureHtml(result,i));
            }
        }else if(min < result.length || max > result.length){
            for(var i=min; i<result.length; i++){
                that.$overflowrow.find(".future_data table#equity_future tbody").append(that._loadmoreFutureHtml(result,i));
            }
            that.$equity_future.find(".load").hide();
        }
        if(that.temp_future){
            that.$sec_max.find("tbody tr").eq(0).after("<tr class='hsirowcon'></tr>");
            that.temp_future = null;
        }
        that._futureRow(data);
        that.$sec_max.find("tbody tr")[0].click();
    },
    _loadmoreFutureHtml : function(result,i) {
        var html = '';
        html+="<tr>"+
            '<td>'+this._filtersVal(result[i].con)+'</td>'+
            '<td>'+this._filtersVal(result[i].ls)+'</td>'+
            '<td>'+this._filtersVal(result[i].nc)+'</td>'+
            '<td>'+this._filtersVal(result[i].se)+'</td>'+
            '<td>'+this._filtersVal(result[i].bd)+'<br>'+this._filtersVal(result[i].as)+'</td>'+
            '<td>'+this._filtersVal(result[i].op)+'</td>'+
            '<td>'+this._filtersVal(result[i].hi)+'<br>'+this._filtersVal(result[i].lo)+'</td>'+
            '<td>'+this._filtersVal(result[i].vo)+'</td>'+
            '<td>'+this._filtersVal(result[i].oi)+'</td>'+
        "</tr>";
        
        return html;
    },
    _filtersVal : function(val){
        var valName;
        if(val){
            valName=val;
        }else{
            valName='-';
        }
        
        return valName;
    },
    _s2ab : function(s){
        if(typeof ArrayBuffer !== 'undefined') {
            var buf = new ArrayBuffer(s.length);
            var view = new Uint8Array(buf);
            for (var i=0; i!==s.length; ++i) view[i] = s.charCodeAt(i) & 0xFF;
            return buf;
        }else{
            var buf = new Array(s.length);
            for (var i=0; i!==s.length; ++i) buf[i] = s.charCodeAt(i) & 0xFF;
            return buf;
        }
    },
    _eTTE : function(id, type, name, fn){
    	var that=this;
    	
        var wb = XLSX.utils.table_to_book(document.getElementById(id), {sheet:"Sheet JS"});
        var wbout = XLSX.write(wb, {bookType:type, bookSST:true, type: 'binary'});
        var fname = fn || name + '.' + type;
        try {
            saveAs(new Blob([that._s2ab(wbout)],{type:"application/octet-stream"}), fname);
        } catch(e) { if(typeof console !== 'undefined') console.log(e, wbout); }
        return wbout;
    },
    
    //
    _dataChartExportFlow: function() {
        var that=this;
        
        var index=that.$equity_future.find("table#equity_future tbody tr.active").index();
        var d=that.curdata.futureslist[index];

        that._showchart(d.ric, d.hc);
        that.$equity_future.find("table#equity_future").attr("data-id",d.ric);
    },
    
    //export futures
    _exportFutures: function() {
        var that=this;
        
        var span=that.$hsirow.find(".interval").attr("data-id");
        var interval=that.$hsirow.find(".hsichart").attr("data-id");
        var ric=that.$equity_future.find("table#equity_future").attr("data-id");
        that.$pageobj.loaddata("getchartdata2", "getchartdata2",
        {
            "span": span,
            "int": interval,
            "ric": ric,
            "token": LabCI.getToken()
        },
        function(result) { //Nov Release
//          console.log(result.data.datalist);
            var html='';
            var flag=that.$hsirow.find(".hsichart .period.selected").html();
            var period = that._getSelectedInterval(); //Nov Release
            if(flag === '5 D'){ //Nov Release
                if (that.lang==='zh_HK'){
                    html+='<tr>'+
                        '<th class="">時間</th>'+
                        '<th class="">最後成交價</th>'+
                        '<th class="">成交數量</th>'+
                        '<th class="">未平倉合約</th>' + 
                    '</tr>';
                }
                else if (that.lang==='chn'){
                    html+='<tr>'+
                        '<th class="">时间</th>'+
                        '<th class="">最后成交价</th>'+
                        '<th class="">成交数量</th>'+
                        '<th class="">未平仓合约</th>' + 
                    '</tr>';
                } else {
                    html+='<tr>'+
                        '<th class="">Time</th>'+
                        '<th class="">Last Traded Price</th>'+
                        '<th class="">Volume</th>'+
                        '<th class="">Open Interest</th>' + 
                    '</tr>';
                }
                
                html+=that._exportFuturesHtml(result.data.datalist,0);
            } else if (period === 0) { //Nov Release
                if (that.lang==='zh_HK'){
                    html+='<tr>'+
                        '<th class="">時間</th>'+
                        '<th class="">最後成交價</th>'+
                        '<th class="">成交數量</th>'+
                    '</tr>';
                }
                else if (that.lang==='chn'){
                    html+='<tr>'+
                        '<th class="">时间</th>'+
                        '<th class="">最后成交价</th>'+
                        '<th class="">成交数量</th>'+
                    '</tr>';
                } else {
                    html+='<tr>'+
                        '<th class="">Time</th>'+
                        '<th class="">Last Traded Price</th>'+
                        '<th class="">Volume</th>'+
                    '</tr>';
                }
                
                html+=that._exportFuturesHtml(result.data.datalist,0);
            }else{
                if (that.lang==='zh_HK'){
                    html+='<tr>'+
                        '<th class="">時間</th>'+
                        '<th class="">結算價</th>'+
                        '<th class="">成交數量</th>'+
                        '<th class="">未平倉合約</th>' + 
                    '</tr>';
                }
                else if (that.lang==='chn'){
                    html+='<tr>'+
                        '<th class="">时间</th>'+
                        '<th class="">结算价</th>'+
                        '<th class="">成交数量</th>'+
                        '<th class="">未平仓合约</th>' + 
                    '</tr>';
                } else {
                    html+='<tr>'+
                        '<th class="">Time</th>'+
                        '<th class="">Settlement Price</th>'+
                        '<th class="">Volume</th>'+
                        '<th class="">Open Interest</th>' + 
                    '</tr>';
                }
                
                html+=that._exportFuturesHtml(result.data.datalist,1);
            }
            
            that.$equity_future.find("#equity_future_export").html(html);
            
            //export
            that._eTTE('equity_future_export','xlsx',''+that.product+'_Futures');
        },
        0,
        {
            datatype: "jsonp"
        });
    },
    
    _exportFuturesHtml: function(data,flag) {
        var that=this;
        
        var b=that._getDateTime(data[data.length-2][0],flag);
//        console.log(b);
        
        var lastdatatime=data[data.length-2][0];
        var daybetween=that._dateDif(lastdatatime);
//        console.log(daybetween);
        
        var html='';
        if (that._getSelectedInterval() === 0) { //Nov Release
            for(var i=1; i<data.length-1; i++){
                html+='<tr>'+
                    '<td>'+that._getDateTime(data[i][0],flag)+'</td>'+
                    '<td>'+data[i][4]+'</td>'+
                    '<td>'+data[i][5]+'</td>'+
                '</tr>';
            };
        }else {
            for(var i=1; i<data.length-1; i++){
                html+='<tr>'+
                    '<td>'+that._getDateTime(data[i][0],flag)+'</td>'+
                    '<td>'+data[i][4]+'</td>'+
                    '<td>'+data[i][5]+'</td>'+
                    '<td>'+data[i][6]+'</td>'+
                '</tr>';
            };
        }
        
        return html;
    },
    
    //get date time
    _getDateTime : function(str,flag){
        var oTime;
        if(flag === 0){
//          1985-04-19 00:00:00
            oTime = Highcharts.dateFormat('%Y/%m/%d %H:%M', new Date(str));
        }else{
//          1985-04-19
            oTime = Highcharts.dateFormat('%Y/%m/%d', new Date(str));
        }

        return oTime;  
    },
    
    _getzf : function(num){
        if(parseInt(num) < 10){  
            num = '0'+num;  
        }  
        return num; 
    },
    
    //day between
    _dateDif : function(enddate){
        var date = new Date().getTime() - enddate; 
        var days    = date / 1000 / 60 / 60 / 24;
        var daysRound   = Math.floor(days);
        var hours    = date/ 1000 / 60 / 60 - (24 * daysRound);
        var hoursRound   = Math.floor(hours);
        var minutes   = date / 1000 /60 - (24 * 60 * daysRound) - (60 * hoursRound);
        var minutesRound  = Math.floor(minutes);
        var seconds   = date/ 1000 - (24 * 60 * 60 * daysRound) - (60 * 60 * hoursRound) - (60 * minutesRound);
        var secondsRound  = Math.floor(seconds);
        var time = "Interval-"+(daysRound+"day-"+hoursRound +"hours-"+minutesRound+"min-"+secondsRound+"second");
        return time;
    },
    
    ////////////////////////////////////////////////////////////////////

    // Build up the UI on-the-fly for different languages
    _setUILabels: function() {
        var that = this;
        var rb = this.pageobj_rb;
        this.$section_table.find(".title__main span").html(rb.msg.title[this.product]);
        this.$hsirow.find(".title").html(rb.msg.nm_s[this.product]);

        var c_lo = LabCI.WP.Derivative.getMsg("loadrow", that.lang);
        this.$loadrow.find(".load").html(c_lo.load);
        this.$loadrow.find(".lasupd").html(c_lo.lastupdate);
//        this.$loadrow.find(".disclaimer").html(c_lo.disclaimer.delayedData);
        
//        var equityMap = LabCI.WP.Derivative.dataQualityMap.equity;
//        if (equityMap[this.product] === "RT"){
////            this.$loadrow.find(".disclaimer").hide();
//            this.$loadrow.find(".disclaimer").html(c_lo.disclaimer.realtimeData);
//        }else{
//            this.$loadrow.find(".disclaimer").html(c_lo.disclaimer.delayedData);
//        }
        
        var c_fu = LabCI.WP.Derivative.getMsg("future", that.lang);
        this.$section_table.find(".textrow").html(c_fu.texrow);
        this.$section_table.find(".ps").html(c_fu.ps);
        this.$section_table.find(".ete").html(c_fu.ete);
        this.$section_table.find(".ds").html(c_fu.ds);
        this.$section_table.find(".ns").html(c_fu.ns);

        this.$section_table.find(".con").html(c_fu.fu_ln.con);
        this.$section_table.find(".ls").html(c_fu.fu_ln.ls);
        this.$section_table.find(".nc").html(c_fu.fu_ln.nc);
        this.$section_table.find(".se").html(c_fu.fu_ln.se);
        this.$section_table.find(".bd").html(c_fu.fu_ln.bd);
        this.$section_table.find(".as").html(c_fu.fu_ln.as);
        this.$section_table.find(".op").html(c_fu.fu_ln.op);
        this.$section_table.find(".hi").html(c_fu.fu_ln.hi);
        this.$section_table.find(".lo").html(c_fu.fu_ln.lo);
        this.$section_table.find(".vo").html(c_fu.fu_ln.vo);
        this.$section_table.find(".oi").html(c_fu.fu_ln.oi);

        var c_hs = LabCI.WP.Derivative.getMsg("hsirow", that.lang);
        this.$hsirow.find(".hi_d").html(c_hs.hi);
        this.$hsirow.find(".lo_d").html(c_hs.lo);
        this.$hsirow.find(".vo_d").html(c_hs.vo);

        var c_op = LabCI.WP.Derivative.getMsg("op", that.lang);
        this.$section_table.find(".options h2").html(c_op.texrow);
        this.$section_table.find(".mon").html(c_op.msmmon);
        this.$section_table.find(".str").html(c_op.msmstr);
        this.$section_table.find(".fr").html(c_op.fr);
        this.$section_table.find(".to").html(c_op.to);
        this.$section_table.find(".optionstext").html(c_op.txt);

        this.$opt.find(".cal").html(c_op.menutitle.cal);
        this.$opt.find(".put").html(c_op.menutitle.put);

        this.$opt.find(".oi").html(c_op.ln.oi);
        this.$opt.find(".vo").html(c_op.ln.vo);
        this.$opt.find(".iv").html(c_op.ln.iv);
        this.$opt.find(".oi").html(c_op.ln.oi);
        this.$opt.find(".bd_as").html(c_op.ln.bd_as);
        this.$opt.find(".ls").html(c_op.ln.ls);
        this.$opt.find(".stk").html(c_op.ln.stk);

        var c_sc = LabCI.WP.Derivative.getMsg("sc", that.lang);
        this.$collist.find(".equity_standard h2").html(c_sc.sctitle);
        this.$collist.find(".equity_tailor h2").html(c_sc.tmctitle);
 
        this.$collist.find(".con").html(c_sc.ln.con);
        this.$collist.find(".ty").html(c_sc.ln.ty);
        this.$collist.find(".le").html(c_sc.ln.le);
        this.$collist.find(".lt").html(c_sc.ln.lt);
        this.$collist.find(".bd").html(c_sc.ln.bd);
        this.$collist.find(".as").html(c_sc.ln.as);
        this.$collist.find(".hi").html(c_sc.ln.hi);
        this.$collist.find(".lo").html(c_sc.ln.lo);
        this.$collist.find(".vo").html(c_sc.ln.vo);        
        this.$collist.find(".equity_sta .loadrow .lasupd").html(c_lo.lastupdate);
        this.$collist.find(".equity_tai .loadrow .lasupd").html(c_lo.lastupdate);

        var c_rb = LabCI.WP.CommonRC.getMsg("period", that.lang);
        
        this.$hsirow.find("#p1d").html(c_rb.p1d);
        this.$hsirow.find("#p5d").html(c_rb.p5d);
        this.$hsirow.find("#p1m").html(c_rb.p1m);
        this.$hsirow.find("#p3m").html(c_rb.p3m);
        this.$hsirow.find("#p6m").html(c_rb.p6m);
        this.$hsirow.find("#p1y").html(c_rb.p1y);
        this.$hsirow.find("#p2y").html(c_rb.p2y);
        this.$hsirow.find("#p5y").html(c_rb.p5y);
        this.$hsirow.find("#p10y").html(c_rb.p10y);
        this.$hsirow.find("#ytd").html(c_rb.ytd);
    }, 

    ////////////////////////////////////////////////////////////////////
    _setUIInterval: function(str,classname) {
        var that = this;
        var html='';
        var arr=str.split(",");
        var interval = LabCI.WP.CommonRC.getMsg("interval", that.lang);
        for(var i=0;i<arr.length;i++){
            for(var j=0;j<interval.length;j++){
                if(i===j){
                    html+='<div class="period">'+interval[arr[i]]+'</div>';
                }
            }
        }
        that.$hsirow.find(".interval").attr("class","interval clearfix "+classname);
        that.$hsirow.find(".interval").html(html);

        that.$hsirow.find(".interval .period").off('click').on('click',function(){
            $(this).addClass("selected").siblings().removeClass("selected");
        });
    },
    // A placeholder for resources, to be defined in separate resource files for specific languages
    PAGEOBJ_RESOURCEBUNDLE: {
        conf: {
            perintsetting: {
                p1d: "0,1,2,3",
                p5d: "2,3",
                p1m: "4",
                p3m: "4,5",
                p6m: "4,5",
                p1y: "4,5,6",
                p2y: "4,5,6",
                p5y: "5,6,7",
                p10y: "6,7",
                ytd: "4,5,6,7"
            },
            intervals: ['min', 'min5', 'min15', 'hourly', 'daily', 'weekly', 'monthly', 'quarterly']

        }
    }

};

})(jQuery);
